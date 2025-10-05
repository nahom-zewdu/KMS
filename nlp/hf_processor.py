"""
Hugging Face Processor for Slackbot Knowledge Management System (KMS).

This script runs a Python worker on Heroku to process Redis Streams (`query_jobs`, `slack_jobs`) from the Go backend (Vercel).
- Queries (`query_jobs`): Processes `@KMS` mentions, generates answers using LLM (distilgpt2) with Supabase context, publishes to `query_results:{query_id}`.
- Ingestion (`slack_jobs`): Extracts entities (PERSON, PROJECT, TICKET) using NER (distilbert-base-cased), populates Supabase `entities`/`edges`, caches results.
- Goals: <100ms query latency, 1K QPS, 99.9% uptime, free-tier (Upstash 10K ops/day, Supabase 500MB).
- Integrates with Go backend using Upstash Redis TCP (sought-perch-5675.upstash.io:6379).
"""

import os
import json
import time
import logging
from uuid import uuid4
from retry import retry
import redis
from langchain_huggingface import HuggingFacePipeline
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from supabase import create_client
from transformers import pipeline

# Configure logging with detailed format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
UPSTASH_REDIS_URL = os.getenv("UPSTASH_REDIS_URL")  # e.g., sought-perch-5675.upstash.io:6379
UPSTASH_REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")

# Initialize Redis client (TCP connection)
try:
    redis_client = redis.Redis(
        host=UPSTASH_REDIS_URL.split(":")[0],  # Extract host
        port=int(UPSTASH_REDIS_URL.split(":")[1]),  # Extract port
        password=UPSTASH_REDIS_TOKEN,
        ssl=True,
        decode_responses=True  # Auto-decode strings
    )
    redis_client.ping()
    logger.info("Successfully connected to Redis at %s", UPSTASH_REDIS_URL)
except Exception as e:
    logger.error("Failed to connect to Redis: %s", e)
    raise

# Initialize Supabase client
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Successfully connected to Supabase")
except Exception as e:
    logger.error("Failed to connect to Supabase: %s", e)
    raise

# Initialize LLMs
# NER for entity extraction (ingestion)
ner_pipeline = pipeline(
    "ner",
    model="distilbert-base-cased",
    tokenizer="distilbert-base-cased",
    aggregation_strategy="simple"
)

# LLM for query answering
query_llm = HuggingFacePipeline.from_model_id(
    model_id="distilgpt2",
    task="text-generation",
    pipeline_kwargs={"max_new_tokens": 100, "temperature": 0.7}
)

# Prompt templates
ner_prompt = PromptTemplate(
    input_variables=["text"],
    template="""Extract entities (PERSON: names like Nahom, PROJECT: APIs/services like github, payment API, TICKET: formats like JIRA-123, Jira #123, PR #123) from: '{text}'.
Output JSON: {{"entities": [{{"type": "person/project/ticket", "name": "extracted", "start": 0, "end": 5}}]}}
Example: Input: "Nahom owns github, Jira #435" -> {{"entities": [{{"type": "person", "name": "Nahom", "start": 0, "end": 5}}, {{"type": "project", "name": "github", "start": 11, "end": 17}}, {{"type": "ticket", "name": "Jira #435", "start": 19, "end": 28}}]}}"""
)

query_prompt = PromptTemplate(
    input_variables=["query", "context"],
    template="""Answer the query: '{query}' using the context: {context}.
Provide a concise answer (max 100 tokens) referencing entities and relationships (e.g., person owns project, ticket).
Example: Query: "Who owns github?" Context: {"entities": [{"type": "person", "name": "Nahom"}, {"type": "project", "name": "github"}], "relationships": [{"source_name": "Nahom", "target_name": "github", "type": "owns", "metadata": {"ticket": "Jira #435"}}]}
Answer: Nahom owns github, Jira #435."""
)

ner_chain = LLMChain(llm=HuggingFacePipeline(pipeline=ner_pipeline), prompt=ner_prompt)
query_chain = LLMChain(llm=query_llm, prompt=query_prompt)

@retry(tries=3, delay=1, backoff=2, logger=logger)
def extract_entities(text: str, record_id: str) -> list:
    """
    Extract entities (PERSON, PROJECT, TICKET) from text using NER.

    Args:
        text (str): Input text to process.
        record_id (str): Unique ID for caching/logging.

    Returns:
        list: List of entities [{"type": str, "name": str, "start": int, "end": int}].

    Raises:
        Exception: If NER fails after retries.
    """
    start = time.time()
    try:
        cache_key = f"nlp:{record_id}"
        cached = redis_client.get(cache_key)
        if cached:
            logger.info("RecordID: %s - Cache hit for entities in %s", record_id, time.time() - start)
            return json.loads(cached)

        output = ner_chain.run(text)
        entities = json.loads(output).get("entities", [])
        redis_client.setex(cache_key, 86400, json.dumps(entities))  # Cache 24 hours
        logger.info("RecordID: %s - Extracted %d entities in %s: %s", record_id, len(entities), time.time() - start, entities)
        return entities
    except Exception as e:
        logger.error("RecordID: %s - NER extraction failed in %s: %s", record_id, time.time() - start, e)
        raise

@retry(tries=3, delay=1, backoff=2, logger=logger)
def query_knowledge_graph(query: str, record_id: str) -> str:
    """
    Answer a query using LLM and Supabase context.

    Args:
        query (str): Query text (e.g., "Who owns github?").
        record_id (str): Unique ID for Pub/Sub and caching.

    Returns:
        str: Answer to the query.

    Raises:
        Exception: If LLM or Supabase query fails after retries.
    """
    start = time.time()
    cache_key = f"query:{record_id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            logger.info("RecordID: %s - Cache hit for query '%s' in %s", record_id, query, time.time() - start)
            return cached

        # Query Supabase for context
        context = {"entities": [], "relationships": []}
        try:
            entities = supabase.table("entities").select("type, name").execute().data
            relationships = supabase.table("edges").select("source_id, target_id, type, metadata").execute().data
            context["entities"] = entities
            context["relationships"] = relationships
            logger.info("RecordID: %s - Fetched Supabase context in %s: %d entities, %d relationships",
                        record_id, time.time() - start, len(entities), len(relationships))
        except Exception as e:
            logger.warning("RecordID: %s - Supabase query failed in %s: %s", record_id, time.time() - start, e)

        # Generate answer with LLM
        answer = query_chain.run(query=query, context=json.dumps(context))
        redis_client.setex(cache_key, 300, answer)  # Cache 5 minutes
        logger.info("RecordID: %s - Generated answer for query '%s' in %s: %s", record_id, query, time.time() - start, answer)
        return answer
    except Exception as e:
        logger.error("RecordID: %s - Query processing failed in %s: %s", record_id, time.time() - start, e)
        return "Unable to process query."

@retry(tries=3, delay=1, backoff=2, logger=logger)
def store_entities_and_relationships(entities: list, record_id: str, text: str) -> None:
    """
    Store entities and relationships in Supabase.

    Args:
        entities (list): List of entities from NER.
        record_id (str): Unique ID for logging.
        text (str): Original text for context.

    Raises:
        Exception: If Supabase insert fails after retries.
    """
    start = time.time()
    try:
        entity_ids = {}
        for entity in entities:
            entity_id = str(uuid4())
            supabase.table("entities").insert({
                "id": entity_id,
                "type": entity["type"],
                "name": entity["name"],
                "metadata": {}
            }).execute()
            entity_ids[entity["name"]] = entity_id
            logger.info("RecordID: %s - Stored entity %s (ID: %s) in %s", record_id, entity["name"], entity_id, time.time() - start)

        relationships = infer_relationships(entities)
        for rel in relationships:
            supabase.table("edges").insert({
                "id": str(uuid4()),
                "source_id": entity_ids[rel["source_name"]],
                "target_id": entity_ids[rel["target_name"]],
                "type": rel["type"],
                "metadata": rel["metadata"]
            }).execute()
            logger.info("RecordID: %s - Stored relationship %s -> %s (%s) in %s",
                        record_id, rel["source_name"], rel["target_name"], rel["type"], time.time() - start)

        if entities:
            supabase.table("raw_data").update({"entity_id": entity_ids[entities[0]["name"]]}).eq("id", record_id).execute()
            logger.info("RecordID: %s - Updated raw_data with entity_id %s in %s", record_id, entity_ids[entities[0]["name"]], time.time() - start)
    except Exception as e:
        logger.error("RecordID: %s - Failed to store entities/relationships for '%s' in %s: %s", record_id, text, time.time() - start, e)
        raise

def infer_relationships(entities: list) -> list:
    """
    Infer relationships (e.g., person owns project) from entities.

    Args:
        entities (list): List of entities [{"type": str, "name": str, "start": int, "end": int}].

    Returns:
        list: List of relationships [{"source_name": str, "target_name": str, "type": str, "metadata": dict}].
    """
    relationships = []
    for i, entity in enumerate(entities):
        if entity["type"] == "person":
            for j in range(i + 1, len(entities)):
                if entities[j]["type"] == "project":
                    ticket = next((e["name"] for e in entities if e["type"] == "ticket"), "")
                    relationships.append({
                        "source_name": entity["name"],
                        "target_name": entities[j]["name"],
                        "type": "owns",
                        "metadata": {"ticket": ticket}
                    })
    return relationships

def main():
    """
    Main worker loop to process Redis Streams (`query_jobs`, `slack_jobs`).

    - `query_jobs`: Process `@KMS` queries, generate answers, publish to `query_results:{query_id}`.
    - `slack_jobs`: Extract entities, store in Supabase `entities`/`edges`, cache results.
    - Batches 10 messages per stream, retries on errors, caches results.
    """
    streams = ["query_jobs", "slack_jobs"]
    while True:
        try:
            start = time.time()
            response = redis_client.xread(streams={stream: "0" for stream in streams}, count=10, block=10000)
            # xread returns a list of (stream, messages) tuples
            for stream, messages in response:
                stream_name = stream
                for message_id, message in messages:
                    # If message is a list of two elements (id, dict), unpack accordingly
                    if isinstance(message, dict):
                        msg_data = message
                    elif isinstance(message, (list, tuple)) and len(message) == 2:
                        msg_data = message[1]
                        message_id = message[0]
                    else:
                        msg_data = {}

                    record_id = msg_data.get("record_id", "")
                    text = msg_data.get("content", "")
                    source = msg_data.get("source", "")
                    logger.info("RecordID: %s - Processing %s message: %s", record_id, stream_name, text)

                    if stream_name == "query_jobs":
                        answer = query_knowledge_graph(text, record_id)
                        redis_client.publish(f"query_results:{record_id}", answer)
                        logger.info("RecordID: %s - Published answer to query_results:%s in %s", record_id, record_id, time.time() - start)
                    elif stream_name == "slack_jobs":
                        entities = extract_entities(text, record_id)
                        store_entities_and_relationships(entities, record_id, text)

                    redis_client.xdel(stream_name, message_id)
                    logger.info("RecordID: %s - Deleted message %s from %s in %s", record_id, message_id, stream_name, time.time() - start)
        except Exception as e:
            logger.error("Redis stream error in %s: %s", time.time() - start, e)
            time.sleep(5)  # Backoff on error
        time.sleep(0.1)  # Avoid tight loop

if __name__ == "__main__":
    main()