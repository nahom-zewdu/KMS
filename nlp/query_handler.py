# query_handler.py
"""
Handles query_jobs → searches knowledge graph → generates natural language answer.
"""
from typing import Dict, Any
from supabase import Client
from redis import Redis
from datetime import datetime, timezone
from engine.llm import llm_infer
from engine.prompt import ENTITY_PROMPT
import logging
import json

ANSWER_PROMPT = """You are a helpful assistant. Answer the question using only the provided context.

Question: {question}
Context: {context}

If no relevant info, say "I don't know."

Answer in 1-2 sentences.
"""

def search_knowledge_graph(supabase: Client, query: str, company_id: str) -> str:
    """Search entities and edges for relevant context."""
    if not company_id or company_id.strip().lower() == "default":
        raise ValueError("A real company_id is required for knowledge retrieval")
    try:
        # Search entities
        entities = (
            supabase.table("entities")
            .select("id,name,type")
            .eq("company_id", company_id)
            .ilike("name", f"%{query.lower()}%")
            .limit(10)
            .execute()
        )
        # Search edges
        edges = (
            supabase.table("edges")
            .select("id,source_id,target_id,type")
            .eq("company_id", company_id)
            .limit(100)
            .execute()
        )

        context = []
        for e in entities.data:
            context.append(f"{e['name']} is a {e['type']}")
        entity_ids = {
            row["id"]: row for row in entities.data or [] if row.get("id")
        }
        edges_by_entity = [
            row for row in (edges.data or [])
            if row.get("source_id") in entity_ids or row.get("target_id") in entity_ids
        ]
        related_ids = {
            value
            for edge in edges_by_entity
            for value in (edge.get("source_id"), edge.get("target_id"))
            if value
        }
        missing_ids = related_ids - set(entity_ids)
        if missing_ids:
            related_entities = (
                supabase.table("entities")
                .select("id,name,type")
                .eq("company_id", company_id)
                .in_("id", list(missing_ids))
                .execute()
            )
            entity_ids.update({
                row["id"]: row for row in (related_entities.data or []) if row.get("id")
            })
        for edge in edges_by_entity:
            source = entity_ids.get(edge.get("source_id"))
            target = entity_ids.get(edge.get("target_id"))
            if source and target:
                context.append(f"{source['name']} {edge['type']} {target['name']}")
        
        return "\n".join(context) if context else "No relevant data."
    except Exception as e:
        logging.error(f"Search failed: {e}")
        return "Search failed."

def handle_query(job: Dict, supabase: Client, redis: Redis) -> None:
    """
    Process query_jobs → search KG → generate answer → publish.
    """
    query_id = job["RecordID"]
    question = job["Content"].strip()
    company_id = str(job.get("CompanyID") or job.get("company_id") or "").strip()
    if not company_id or company_id.lower() == "default":
        raise ValueError("company_id is required for query processing")
    logging.info(f"Query | {query_id} | {question}")

    if not question:
        answer = "Please ask a clear question."
    else:
        context = search_knowledge_graph(supabase, question, company_id)
        prompt = ANSWER_PROMPT.format(question=question, context=context)
        answer = llm_infer(prompt) or "I don't know."

    # Store in raw_data for audit
    created_at = job.get("CreatedAt") or datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("raw_data").insert({
            "id": f"{query_id}-query",
            "source": "query",
            "content": f"Q: {question} | A: {answer}",
            "record_id": query_id,
            "company_id": company_id,
            "created_at": created_at
        }).execute()
    except Exception as e:
        logging.error(f"Failed to store query result: {e}")

    # Publish answer
    try:
        redis.publish(f"query_results:{query_id}", answer)
        logging.info(f"Answer published | {query_id} | {answer}")
    except Exception as e:
        logging.error(f"Failed to publish answer: {e}")
