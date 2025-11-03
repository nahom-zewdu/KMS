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

def search_knowledge_graph(supabase: Client, query: str) -> str:
    """Search entities and edges for relevant context."""
    try:
        # Search entities
        entities = supabase.table("entities").select("text,type").ilike("text", f"%{query.lower()}%").limit(10).execute()
        # Search edges
        edges = supabase.table("edges").select("source,target,type").ilike("source", f"%{query.lower()}%").limit(10).execute()
        
        context = []
        for e in entities.data:
            context.append(f"{e['text']} is a {e['type']}")
        for e in edges.data:
            context.append(f"{e['source']} {e['type']} {e['target']}")
        
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
    logging.info(f"Query | {query_id} | {question}")

    if not question:
        answer = "Please ask a clear question."
    else:
        context = search_knowledge_graph(supabase, question)
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
