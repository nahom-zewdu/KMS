# utils/redis.py
"""
Redis client with connection pooling and retry.
"""

import redis
import logging

def init_redis(addr: str, password: str) -> redis.Redis:
    """
    Initialize Redis client with connection pooling.
    """
    if not addr or not password:
        raise EnvironmentError("REDIS_ADDR and REDIS_PASSWORD must be set")
    
    try:
        client = redis.Redis(
            host=addr,
            port=6379,
            password=password,
            db=0,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
        # Test connection
        client.ping()
        logging.info(f"Redis connected to {addr}")
        return client
    except Exception as e:
        logging.error(f"Failed to connect to Redis: {e}")
        raise
