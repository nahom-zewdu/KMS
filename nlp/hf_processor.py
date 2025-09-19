import os
import json
import time
import logging
from langchain.llms import HuggingFaceHub
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from supabase import create_client
import redis
import uuid
from retry import retry

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

# Initialize clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.Redis.from_url(UPSTASH_URL, password=UPSTASH_TOKEN)

# Initialize LLM
llm = HuggingFaceHub(
    repo_id="dslim/bert-base-NER",
    huggingfacehub_api_token=HF_API_TOKEN,
    model_kwargs={"temperature": 0.0, "max_length": 512}
)

# Prompt template (versioned in prompts/)
prompt_template = PromptTemplate(
    input_variables=["text"],
    template="""Extract entities (PERSON: names like Nahom, PROJECT: APIs/services like github, payment API, TICKET: formats like JIRA-123, Jira #123, PR #123) from: '{text}'.
Output JSON: {"entities": [{"type": "person/project/ticket", "name": "extracted", "start": 0, "end": 5}]}
Example: Input: "Nahom owns github, Jira #435" -> {"entities": [{"type": "person", "name": "Nahom", "start": 0, "end": 5}, {"type": "project", "name": "github", "start": 11, "end": 17}, {"type": "ticket", "name": "Jira #435", "start": 19, "end": 28}]}"""
)

chain = LLMChain(llm=llm, prompt=prompt_template)

@retry(tries=3, delay=1, backoff=2, logger=logger)
def extract_entities(text):
    """Extract entities using Hugging Face LLM with retry."""
    try:
        output = chain.run(text)
        entities = json.loads(output).get("entities", [])
        return entities
    except Exception as e:
        logger.error(f"LLM extraction failed for text '{text}': {e}")
        raise

def infer_relationships(entities):
    """Infer relationships (e.g., person owns project) from entities."""
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

def process_raw_data():
    """Process raw_data from Supabase, extract entities, populate knowledge graph."""
    response, _, err = supabase.table("raw_data").select("*").is_("entity_id", None).limit(100).execute()
    if err:
        logger.error(f"Supabase fetch error: {err}")
        return
    
    for record in response:
        text = record["content"]
        record_id = record["id"]
        try:
            # Extract entities
            entities = extract_entities(text)
            logger.info(f"Extracted entities for record {record_id}: {entities}")
            
            # Store entities
            entity_ids = {}
            for entity in entities:
                entity_id = str(uuid.uuid4())
                supabase.table("entities").insert({
                    "id": entity_id,
                    "type": entity["type"],
                    "name": entity["name"],
                    "metadata": {}
                }).execute()
                entity_ids[entity["name"]] = entity_id
            
            # Update raw_data with first entity_id
            if entities:
                supabase.table("raw_data").update({"entity_id": entity_ids[entities[0]["name"]]}).eq("id", record_id).execute()
            
            # Store relationships
            relationships = infer_relationships(entities)
            for rel in relationships:
                supabase.table("edges").insert({
                    "source_id": entity_ids[rel["source_name"]],
                    "target_id": entity_ids[rel["target_name"]],
                    "type": rel["type"],
                    "metadata": rel["metadata"]
                }).execute()
            
            # Cache result
            redis_client.setex(f"nlp:{record_id}", 86400, json.dumps(entities))
            logger.info(f"Cached NLP result for record {record_id}")
        except Exception as e:
            logger.error(f"Processing failed for record {record_id}: {e}")
            # Fallback: Keyword search or skip
            continue

def main():
    """Run worker to process Redis Streams."""
    while True:
        try:
            messages = redis_client.xread({"slack_jobs": "$"}, block=1000, count=10)
            for _, entries in messages:
                for entry_id, entry in entries:
                    text = entry.get(b"content", b"").decode("utf-8")
                    record_id = entry.get(b"record_id", b"").decode("utf-8")
                    process_raw_data()  # Process all unprocessed records
                    redis_client.xdel("slack_jobs", entry_id)
        except Exception as e:
            logger.error(f"Redis stream error: {e}")
            time.sleep(5)  # Backoff on error
        time.sleep(1)  # Avoid tight loop

if __name__ == "__main__":
    main()