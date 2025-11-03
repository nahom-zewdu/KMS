# utils/logger.py
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_structured_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d'
    )
    handler.setFormatter(formatter)
    logger.handlers = [handler]
