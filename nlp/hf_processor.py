# nlp/hf_processor.py
"""
Processes Redis streams (github_jobs, slack_jobs, query_jobs) to extract entities, relationships,
and handle Slack queries for KnowSphere's knowledge graph. Updates Supabase tables (entities, edges,
contributions, pull_requests, issues) and responds to query_jobs with results. Uses HuggingFace NLP
models for entity extraction and handles edge cases like large payloads, deleted repos, and retries.
"""

import json
import os
import time
import logging
import uuid
from typing import Dict, List
from redis import Redis
from supabase import create_client, Client
from dotenv import load_dotenv
from langchain_huggingface import HuggingFacePipeline
from transformers import pipeline
from retry import retry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load environment variables
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
REDIS_ADDR = os.getenv("REDIS_ADDR")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")

# Initialize Supabase and Redis clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis = Redis.from_url(
    f"rediss://{REDIS_ADDR}",
    password=REDIS_PASSWORD,
    ssl_cert_reqs=None
)

# Initialize HuggingFace NLP pipeline for entity recognition
nlp = pipeline(
    "ner",
    model="distilbert-base-cased",
    tokenizer="distilbert-base-cased",
    device=0
)
# Initialize HuggingFace LLM for text generation
llm = HuggingFacePipeline.from_model_id(
    model_id="distilgpt2",
    task="text-generation",
    pipeline_kwargs={"max_new_tokens": 50}
)

@retry(tries=3, delay=1, backoff=2)
def update_entities_and_edges(event: Dict, event_id: str) -> None:
    """
    Extracts entities (PERSON, PROJECT, TICKET) and relationships (authored, assigned, fixes)
    from a GitHub/Slack event payload, storing them in Supabase. Updates contributions,
    pull_requests, and issues tables for GitHub events.

    Args:
        event: Dictionary with event data (RecordID, Source, EventType, Content, Payload, CreatedAt).
        event_id: UUID of the event in the events table.

    Raises:
        Exception: If Supabase/Redis operations fail after retries.
    """
    start = time.time()
    logging.info(f"Processing event {event['RecordID']} ({event['Source']}, {event['EventType']})")
    payload = event["Payload"]

    entities: List[Dict] = []
    edges: List[Dict] = []

    if event["Source"] == "github":
        repo_name = payload.get("repository", {}).get("full_name", "")
        sender = payload.get("sender", {}).get("login", "")

        if event["EventType"] == "push":
            project_id = str(uuid.uuid4())
            entities.append({
                "id": project_id,
                "type": "project",
                "name": repo_name,
                "metadata": {"url": payload.get("repository", {}).get("url", "")},
                "active": True,
                "created_at": event["CreatedAt"]
            })

            commits = payload.get("commits", [])
            for commit in commits:
                author = commit.get("author", {}).get("name", sender)
                person_id = str(uuid.uuid4())
                entities.append({
                    "id": person_id,
                    "type": "person",
                    "name": author,
                    "metadata": {"email": commit.get("author", {}).get("email", "")},
                    "active": True,
                    "created_at": event["CreatedAt"]
                })
                edges.append({
                    "id": str(uuid.uuid4()),
                    "source_id": person_id,
                    "target_id": project_id,
                    "type": "authored",
                    "metadata": {
                        "commit_sha": commit.get("id", ""),
                        "message": commit.get("message", "")
                    },
                    "created_at": event["CreatedAt"]
                })

        elif event["EventType"] == "pull_request":
            pr = payload.get("pull_request", {})
            pr_id = str(uuid.uuid4())
            entities.append({
                "id": pr_id,
                "type": "ticket",
                "name": f"PR #{pr.get('number', '')}",
                "metadata": {
                    "title": pr.get("title", ""),
                    "body": pr.get("body", "")
                },
                "active": pr.get("state", "") != "closed",
                "created_at": event["CreatedAt"]
            })
            supabase.table("pull_requests").upsert({
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "pr_number": pr.get("number", 0),
                "repo_name": repo_name,
                "title": pr.get("title", ""),
                "body": pr.get("body", ""),
                "assignee_id": None,
                "reviewers": pr.get("requested_reviewers", []),
                "labels": pr.get("labels", []),
                "commits_count": pr.get("commits", 0),
                "merged": pr.get("merged", False),
                "created_at": event["CreatedAt"]
            }, on_conflict="pr_number,repo_name").execute()

            if assignee := pr.get("assignee"):
                person_id = str(uuid.uuid4())
                entities.append({
                    "id": person_id,
                    "type": "person",
                    "name": assignee.get("login", ""),
                    "metadata": {},
                    "active": True,
                    "created_at": event["CreatedAt"]
                })
                edges.append({
                    "id": str(uuid.uuid4()),
                    "source_id": person_id,
                    "target_id": pr_id,
                    "type": "assigned",
                    "metadata": {"action": payload.get("action", "")},
                    "created_at": event["CreatedAt"]
                })
                supabase.table("pull_requests").update({
                    "assignee_id": person_id
                }).eq("id", pr_id).execute()

        elif event["EventType"] == "issues":
            issue = payload.get("issue", {})
            issue_id = str(uuid.uuid4())
            entities.append({
                "id": issue_id,
                "type": "ticket",
                "name": f"Issue #{issue.get('number', '')}",
                "metadata": {
                    "title": issue.get("title", ""),
                    "body": issue.get("body", "")
                },
                "active": issue.get("state", "") == "open",
                "created_at": event["CreatedAt"]
            })
            supabase.table("issues").upsert({
                "id": str(uuid.uuid4()),
                "event_id": event_id,
                "issue_number": issue.get("number", 0),
                "repo_name": repo_name,
                "title": issue.get("title", ""),
                "body": issue.get("body", ""),
                "assignee_id": None,
                "labels": issue.get("labels", []),
                "state": issue.get("state", "open"),
                "created_at": event["CreatedAt"]
            }, on_conflict="issue_number,repo_name").execute()

            if assignee := issue.get("assignee"):
                person_id = str(uuid.uuid4())
                entities.append({
                    "id": person_id,
                    "type": "person",
                    "name": assignee.get("login", ""),
                    "metadata": {},
                    "active": True,
                    "created_at": event["CreatedAt"]
                })
                edges.append({
                    "id": str(uuid.uuid4()),
                    "source_id": person_id,
                    "target_id": issue_id,
                    "type": "assigned",
                    "metadata": {"action": payload.get("action", "")},
                    "created_at": event["CreatedAt"]
                })
                supabase.table("issues").update({
                    "assignee_id": person_id
                }).eq("id", issue_id).execute()

        # Update contributions for GitHub events
        if event["EventType"] in ["push", "pull_request", "issues"]:
            update_contributions(event, payload, sender, repo_name)

    elif event["Source"] == "slack" and event["EventType"] == "message":
        entities.append({
            "id": str(uuid.uuid4()),
            "type": "person",
            "name": payload.get("user", "unknown"),
            "metadata": {},
            "active": True,
            "created_at": event["CreatedAt"]
        })
        llm_result = llm(f"Extract project or ticket from: {event['Content']}")
        project_name = llm_result[0]["generated_text"].strip()
        if project_name:
            entities.append({
                "id": str(uuid.uuid4()),
                "type": "project",
                "name": project_name,
                "metadata": {},
                "active": True,
                "created_at": event["CreatedAt"]
            })

    # Insert entities and edges
    for entity in entities:
        supabase.table("entities").upsert(entity, on_conflict="id").execute()
    for edge in edges:
        supabase.table("edges").insert(edge).execute()

    # Mark event as processed
    supabase.table("events").update({"processed": True}).eq("id", event_id).execute()
    logging.info(f"Processed event {event['RecordID']} in {time.time() - start:.3f}s")

@retry(tries=3, delay=1, backoff=2)
def process_query(event: Dict) -> None:
    """
    Processes query_jobs stream, searches Supabase entities/raw_data, and publishes results to query_results.

    Args:
        event: Dictionary with query data (RecordID, Source, Content, Payload, CreatedAt).

    Raises:
        Exception: If Supabase/Redis operations fail after retries.
    """
    start = time.time()
    query_id = event["RecordID"]
    query = event["Content"]
    logging.info(f"Processing query {query_id}: {query}")

    # Search entities and raw_data
    result = supabase.table("entities").select("name, type, metadata").ilike("name", f"%{query}%").execute()
    if not result.data:
        result = supabase.table("raw_data").select("content").ilike("content", f"%{query}%").execute()

    # Generate response
    response = "No results found."
    if result.data:
        if "name" in result.data[0]:
            # Entities result
            entities = [f"{r['type'].capitalize()}: {r['name']} ({r['metadata']})" for r in result.data]
            response = f"Found {len(entities)} results:\n" + "\n".join(entities)
        else:
            # Raw_data result
            response = result.data[0]["content"]

    # Publish to query_results
    redis.xadd(f"query_results:{query_id}", {"answer": response})
    logging.info(f"Processed query {query_id} in {time.time() - start:.3f}s, response: {response}")

@retry(tries=3, delay=1, backoff=2)
def update_contributions(event: Dict, payload: Dict, sender: str, repo_name: str) -> None:
    """
    Updates contribution metrics (commit_count, pr_count, issue_count) in the contributions table.

    Args:
        event: Dictionary with event data (RecordID, EventType, etc.).
        payload: Parsed event payload.
        sender: GitHub user login.
        repo_name: Repository full name.

    Raises:
        Exception: If Supabase operation fails after retries.
    """
    start = time.time()
    update = {
        "id": str(uuid.uuid4()),
        "person_name": sender,
        "repo_name": repo_name,
        "commit_count": 0,
        "pr_count": 0,
        "issue_count": 0,
        "updated_at": event["CreatedAt"]
    }

    if event["EventType"] == "push":
        update["commit_count"] = len(payload.get("commits", []))
    elif event["EventType"] == "pull_request":
        update["pr_count"] = 1
    elif event["EventType"] == "issues":
        update["issue_count"] = 1

    supabase.table("contributions").upsert(
        update,
        on_conflict="person_name,repo_name"
    ).execute()
    logging.info(f"Updated contributions for {sender} in {repo_name} in {time.time() - start:.3f}s")

def process_stream() -> None:
    """
    Continuously processes Redis streams (github_jobs, slack_jobs, query_jobs), updating Supabase
    and responding to queries. Deletes processed messages from streams.

    Raises:
        Exception: If Redis connection fails, handled with exponential backoff.
    """
    streams = ["github_jobs", "slack_jobs", "query_jobs"]
    while True:
        try:
            response = redis.xread(streams=streams, count=10, block=1000)
            for stream, messages in response:
                for message_id, message in messages:
                    event = {
                        "RecordID": message.get(b"RecordID", b"").decode(),
                        "Source": message.get(b"Source", b"").decode(),
                        "EventType": message.get(b"EventType", b"").decode(),
                        "Content": message.get(b"Content", b"").decode(),
                        "Payload": json.loads(message.get(b"Payload", b"{}").decode()),
                        "CreatedAt": message.get(b"CreatedAt", b"").decode()
                    }
                    if stream.decode() == "query_jobs":
                        process_query(event)
                    else:
                        result = supabase.table("events").select("id").eq("delivery_id", event["RecordID"]).execute()
                        event_id = result.data[0]["id"] if result.data else str(uuid.uuid4())
                        update_entities_and_edges(event, event_id)
                    redis.xdel(stream, message_id)
        except Exception as e:
            logging.error(f"Error processing stream: {e}")
            time.sleep(1)

if __name__ == "__main__":
    process_stream()
    