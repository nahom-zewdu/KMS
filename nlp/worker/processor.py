# worker/processor.py
"""
Main processor: manages lifecycle, routing, and error handling.
"""
import logging
from .consumer import RedisStreamConsumer
from .ingestion import IngestionHandler
from .query import QueryHandler
from .baseline import BaselineHandler
from .codebase_analysis import CodebaseAnalysisHandler
from utils import setup_structured_logging
from query_engine.vector.retriever import get_embedder

logger = logging.getLogger("processor")

class NLPProcessor:
    def __init__(self):
        setup_structured_logging()

        logging.info("=== NLPProcessor initialization ===")

        slack_handler = IngestionHandler()
        logging.info("Slack handler created.")

        github_handler = IngestionHandler()
        logging.info("GitHub handler created.")

        query_handler = QueryHandler()
        logging.info("Query handler created.")

        baseline_handler = BaselineHandler()
        logging.info("Baseline handler created.")

        codebase_analysis_handler = CodebaseAnalysisHandler()
        logging.info("Codebase analysis handler created.")

        self.consumer = RedisStreamConsumer(
            streams=[
                "slack_jobs",
                "github_jobs",
                "query_jobs",
                "codebase_baseline_jobs",
                "codebase_analysis_jobs",
            ],
            group="kms",
            handlers={
                "slack_jobs": slack_handler,
                "github_jobs": github_handler,
                "query_jobs": query_handler,
                "codebase_baseline_jobs": baseline_handler,
                "codebase_analysis_jobs": codebase_analysis_handler,
            },
        )

        logging.info("Redis consumer created.")

    def run(self):
        logging.info("KMS NLP Processor starting...")
        self.consumer.start()

    def stop(self):
        logging.info("Stopping processor...")
        self.consumer.stop()
