import logging
from retry import retry
import json

logger = logging.getLogger(__name__)

@retry(tries=3, delay=1, backoff=2, logger=logger)
def call_llm(chain, text):
    """Call LLM with retries."""
    try:
        output = chain.run(text)
        return json.loads(output)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise