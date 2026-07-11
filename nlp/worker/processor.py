# worker/processor.py
"""
Main processor: manages lifecycle, routing, and error handling.
"""
import logging
from .consumer import RedisStreamConsumer
from .ingestion import IngestionHandler
from .query import QueryHandler
from .baseline import BaselineHandler
from utils import setup_structured_logging
from query_engine.vector.retriever import get_embedder

logger = logging.getLogger("processor")

class NLPProcessor:
    def __init__(self):
        setup_structured_logging()
        logging.info("Initializing NLP Processor...")
        
        # Pre-load sentence transformer model on startup (~15s one-time cost)
        logging.info("Pre-loading sentence transformer model...")
        try:
            model = get_embedder()
            logging.info(f"✓ Embedder loaded: {model.get_sentence_embedding_dimension()} dimensions")
        except Exception as e:
            logging.warning(f"Failed to pre-load embedder: {e}. Will load on first query.")

        self.consumer = RedisStreamConsumer(
            streams=["slack_jobs", "github_jobs", "query_jobs", "codebase_baseline_jobs"],
            group="kms",
            handlers={
                "slack_jobs": IngestionHandler(),
                "github_jobs": IngestionHandler(),
                "query_jobs": QueryHandler(),
                "codebase_baseline_jobs": BaselineHandler(),
            }
        )

    def run(self):
        logging.info("KMS NLP Processor starting...")
        self.consumer.start()

    def stop(self):
        logging.info("Stopping processor...")
        self.consumer.stop()
