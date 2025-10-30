# nlp/main.py
# Purpose: Main loop for processing Redis streams (slack_jobs, github_jobs, query_jobs).
# It delegates to NER/RE/query modules and updates Supabase, handling retries and edge cases.

import json
import os
import time
import logging
from dotenv import load_dotenv
from redis import Redis
from utils import init_supabase, init_redis, log_error
from nlp.ner import extract_entities
from nlp.re import extract_relations
from nlp.query_handler import handle_query

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

load_dotenv()
REDIS_ADDR = os.getenv("REDIS_ADDR")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

redis = init_redis(REDIS_ADDR, REDIS_PASSWORD)
supabase = init_supabase()

streams = {"slack_jobs": "$", "github_jobs": "$", "query_jobs": "$"}

def main():
    logging.info("Starting KMS NLP Processor")
    while True:
        try:
            # Read 10 messages from streams (block for 1s)
            response = redis.xread(streams=streams, count=10, block=1000)
            if not response:
                continue

            for stream_name, messages in response:
                for message_id, message_data in messages:
                    try:
                        job = {
                            "RecordID": message_data.get("RecordID", ""),
                            "Source": message_data.get("Source", ""),
                            "EventType": message_data.get("EventType", ""),
                            "Content": message_data.get("Content", ""),
                            "Payload": json.loads(message_data.get("Payload", "{}")),
                            "CreatedAt": message_data.get("CreatedAt", "")
                        }
                        if stream_name == "query_jobs":
                            handle_query(job, supabase, redis)
                        else:
                            entities = extract_entities(job["Content"])
                            relations = extract_relations(job["Content"], entities)
                            for entity in entities:
                                entity["record_id"] = job["RecordID"]
                                entity["source"] = job["Source"]
                                entity["created_at"] = job["CreatedAt"]
                                supabase.table("entities").insert(entity).execute()
                            for relation in relations:
                                relation["record_id"] = job["RecordID"]
                                relation["source"] = job["Source"]
                                relation["created_at"] = job["CreatedAt"]
                                supabase.table("edges").insert(relation).execute()
                            supabase.table("events").update({"processed": True}).eq("delivery_id", job["RecordID"]).execute()
                        
                            # Acknowledge and delete message
                            redis.xack(stream_name, "kms", message_id)
                            redis.xdel(stream_name, message_id)
                    except Exception as e:
                        log_error(f"Failed to process message {message_id} in {stream_name}: {e}")
        except Exception as e:
            log_error(f"Failed to read streams: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
