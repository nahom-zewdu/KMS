# nlp/query_handler.py
# Purpose: Handles query_jobs stream, searches Supabase, and generates answers using free LLM.

import json
import logging
import time
from typing import Dict
from langchain_huggingface import HuggingFacePipeline
from supabase import Client
from redis import Redis

llm = HuggingFacePipeline.from_model_id(
    model_id="distilgpt2",
    task="text-generation",
    pipeline_kwargs={"max_new_tokens": 50},
    device=-1
)

def handle_query(job: Dict, supabase: Client) -> None:
    """
    Processes a query job, searches Supabase, and generates an answer using LLM.
    
    Args:
        job: Dictionary with query data (RecordID, Source, Content, Payload, CreatedAt).
        supabase: Supabase client for querying.
    
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
        result = supabase.table("entities").select("*").ilike("name", f"%{content.lower()}%").execute()
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

    # Publish to query_results
    try:
        redis.xadd(f"query_results:{query_id}", {"answer": answer})
        logging.info(f"Published answer for {query_id}: {answer}")
    except Exception as e:
        logging.error(f"QueryID: {query_id} - Failed to publish to Redis: {e}")

    logging.info(f"Processed query {query_id} in {time.time() - start:.3f}s")
