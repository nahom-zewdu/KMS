# nlp/query_handler.py
# Purpose: Handles query_jobs stream, searches Supabase, and generates answers using free LLM.

from langchain_huggingface import HuggingFacePipeline
from supabase import Client

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
    logging.info(f"Processing query {query_id}: {content}")

    # Search Supabase
    result = supabase.table("entities").select("*").ilike("name", f"%{content}%").execute()
    if not result.data:
        result = supabase.table("raw_data").select("*").ilike("content", f"%{content}%").execute()

    # Generate answer with LLM
    if result.data:
        context = json.dumps(result.data, indent=2)
        prompt = f"Query: {content}\nContext: {context}\nAnswer:"
        answer = llm(prompt)[0]["generated_text"]
    else:
        answer = "No results found."

    # Publish to query_results
    redis.xadd(f"query_results:{query_id}", {"answer": answer})
    logging.info(f"Processed query {query_id} in {time.time() - start:.3f}s, answer: {answer}")