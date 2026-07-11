# nlp/main.py
"""
KMS NLP Processor — Clean, minimal entrypoint.
"""
from worker.processor import NLPProcessor
import signal
import logging

def signal_handler(signum, frame):
    logging.info("Shutdown signal received.")
    processor.stop()

if __name__ == "__main__":
    processor = NLPProcessor()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    processor.run()
