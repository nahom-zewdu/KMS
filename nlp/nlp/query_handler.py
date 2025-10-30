# nlp/query_handler.py
# Purpose: Handles query_jobs stream, searches Supabase, and generates answers using free LLM.

# nlp/query_handler.py
from typing import Dict
import json
import logging
import time

from langchain_huggingface import HuggingFacePipeline
from supabase import Client
from redis import Redis

llm = HuggingFacePipeline.from_model_id(
    model_id="distilgpt2",
    task="text-generation",
    pipeline_kwargs={"max_new_tokens": 50},
    device=-1
)

def handle_query(job: Dict, supabase: Client, redis: Redis) -> None:
    """
    Processes a query job, searches Supabase, and generates an answer using LLM.
    
    Args:
        job: Dictionary with query data (RecordID, Source, Content, Payload, CreatedAt).
        supabase: Supabase client for querying.
        redis: Redis client for publishing results.
    
    Returns:
        None (publishes to query_results via Redis).
    """
    start = time.time()
    query_id = job["RecordID"]
    content = job["Content"]
    logging.info(f"Processing query {query_id}: {content}")

    # Search Supabase (LIMIT RESULTS)
    try:
        result = supabase.table("entities").select("*").ilike("name", f"%{content.lower()}%").limit(3).execute()
        if not result.data:
            result = supabase.table("raw_data").select("*").ilike("content", f"%{content.lower()}%").limit(5).execute()
        
        # TRUNCATE CONTEXT
        context_parts = []
        for item in result.data:
            if isinstance(item, dict):
                name = item.get("name") or item.get("content", "")[:50]
                context_parts.append(name)
        context = " | ".join(context_parts[:3])  # Max 3 items
        if not context:
            context = "No relevant data found."
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Supabase error: {e}")
        context = "No relevant data found."

    # Generate answer with LLM
    prompt = prompt = f"""You are a helpful assistant. Answer the user's question based on the provided context.
            Question: {content}
            Context: {context}
            Provide a short, direct answer:"""
    try:
        answer = llm.invoke(prompt).split("Answer:")[-1].strip()
    except Exception as e:
        logging.error(f"QueryID: {query_id} - LLM error: {e}")
        answer = "No results found."

    created_at = job.get("CreatedAt")
    if not created_at or created_at == "":
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    # Store in raw_data
    try:
        supabase.table("raw_data").insert({
            "id": query_id + "-query",
            "source": "query",
            "content": f"Q: {content} | A: {answer}",
            "record_id": query_id,
            "event_id": None,
            "created_at": created_at
        }).execute()
        logging.info(f"QueryID: {query_id} - Stored in {time.time() - start:.3f}s")
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Store error: {e}")

    # PUBLISH TO PUB/SUB
    try:
        redis.publish(f"query_results:{query_id}", answer)
        logging.info(f"QueryID: {query_id} - Published: {answer}")
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Publish error: {e}")
