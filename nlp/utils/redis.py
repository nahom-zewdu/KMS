# utils/redis.py
"""
Redis client with TLS support for Upstash.
"""
import os
import redis
import logging
from dotenv import load_dotenv

load_dotenv()

def init_redis(url = os.getenv("REDIS_URL")) -> redis.Redis:
    """
    Initialize Redis client using REDIS_URL (rediss:// for TLS).
    """
    
    if not url:
        raise EnvironmentError("REDIS_URL must be set in .env (use rediss://)")

    try:
        client = redis.from_url(
            url,
            decode_responses=True,
            ssl_cert_reqs="required"  # Enforce TLS
        )
        # Test connection
        client.ping()
        logging.info(f"Redis connected via TLS: {url.split('@')[1].split(':')[0]}")
        return client
    except Exception as e:
        logging.error(f"Failed to connect to Redis: {e}")
        raise
