# worker/processor.py
"""
Main processor: manages lifecycle, routing, and error handling.
"""
import logging
from .consumer import RedisStreamConsumer
from .ingestion import IngestionHandler
from .query import QueryHandler
from utils import setup_structured_logging

logger = logging.getLogger("processor")

class NLPProcessor:
    def __init__(self):
        setup_structured_logging()
        logging.info("Initializing NLP Processor...")

        self.consumer = RedisStreamConsumer(
            streams=["slack_jobs", "github_jobs", "query_jobs"],
            group="kms",
            handlers={
                "slack_jobs": IngestionHandler(),
                "github_jobs": IngestionHandler(),
                "query_jobs": QueryHandler()
            }
        )

    def run(self):
        logging.info("KMS NLP Processor starting...")
        self.consumer.start()

    def stop(self):
        logging.info("Stopping processor...")
        self.consumer.stop()
