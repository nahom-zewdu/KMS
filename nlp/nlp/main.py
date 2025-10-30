# nlp/main.py
# Purpose: Main loop for processing Redis streams (slack_jobs, github_jobs, query_jobs).
# It delegates to NER/RE/query modules and updates Supabase, handling retries and edge cases.

import json
import os
import time
import logging
import datetime
from dotenv import load_dotenv
from utils import init_supabase, init_redis, log_error
from nlp.ner import extract_entities
from nlp.re import extract_relations
from nlp.query_handler import handle_query

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
            response = redis.xread(streams=streams, count=10, block=1000)
            if not response:
                continue

            for stream_name, messages in response:
                for message_id, message_data in messages:
                    try:
                        raw_data = message_data.get("data")
                        if not raw_data:
                            logging.warning(f"Empty data field in message {message_id} from {stream_name}")
                            continue

                        payload = json.loads(raw_data)
                        job = {
                            "RecordID": payload.get("RecordID") or payload.get("record_id", ""),
                            "Source": payload.get("Source") or payload.get("source", ""),
                            "EventType": payload.get("EventType") or payload.get("event_type", ""),
                            "Content": payload.get("Content") or payload.get("content", ""),
                            "Payload": payload.get("Payload") or payload.get("payload", {}),
                            "CreatedAt": payload.get("CreatedAt") or payload.get("created_at", "")
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
