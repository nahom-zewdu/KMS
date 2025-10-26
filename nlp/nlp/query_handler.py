# nlp/query_handler.py
# Purpose: Handles query_jobs stream, searches Supabase, and generates answers using free LLM.

from typing import Dict
from langchain_huggingface import HuggingFacePipeline
from supabase import Client
from redis import Redis

import json
import logging
import time

llm = HuggingFacePipeline.from_model_id(
    model_id="distilgpt2",
    task="text-generation",
    pipeline_kwargs={"max_new_tokens": 50},
    device=-1
)

def handle_query(job: Dict, supabase: Client, redis: 'Redis') -> None:
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
    channel = job["Payload"].get("channel", "")
    logging.info(f"Processing query {query_id}-{channel}: {content}")

    # Search Supabase
    try:
        result = supabase.table("entities").select("*").ilike("text", f"%{content.lower()}%").execute()
        if not result.data:
            result = supabase.table("raw_data").select("*").ilike("content", f"%{content.lower()}%").execute()
        context = json.dumps(result.data, indent=2) if result.data else "No relevant data found."
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Failed to query Supabase: {e}")
        context = "No relevant data found."

    # Generate answer with LLM
    prompt = f"Query: {content}\nContext: {context}\nAnswer:"
    try:
        answer = llm(prompt)[0]["generated_text"].split("Answer:")[-1].strip()
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Failed to generate answer: {e}")
        answer = "No results found."

    # Store in Supabase
    try:
        supabase.table("query_results").insert({
            "id": f"{query_id}-{channel}",
            "query": content,
            "response": answer,
            "channel": channel,
            "thread_ts": job["Payload"].get("thread_ts", ""),
            "created_at": job["CreatedAt"]
        }).execute()
        logging.info(f"Stored query result for {query_id}-{channel} in {time.time() - start:.3f}s")
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Failed to store query result: {e}")

    # Publish to Redis
    try:
        redis.xadd(f"query_results:{query_id}", {"answer": answer})
        logging.info(f"Published answer for {query_id}: {answer}")
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Failed to publish to Redis: {e}")
