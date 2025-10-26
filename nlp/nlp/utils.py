# nlp/utils.py
# Purpose: Utilities for logging, Supabase/Redis initialization, and error handling.

import logging
from dotenv import load_dotenv
from redis import Redis
from supabase import create_client, Client
from os import getenv

def init_supabase() -> Client:
    """
    Initializes Supabase client.

    Returns:
        Supabase client.
    """
    load_dotenv()
    url = getenv("SUPABASE_URL")
    key = getenv("SUPABASE_KEY")
    client = create_client(url, key)
    logging.info(f"Initialized Supabase client at {url}")
    return client

def init_redis(addr: str, password: str) -> Redis:
    """
    Initializes Redis client.

    Args:
        addr: Redis address (e.g., sought-perch-5675.upstash.io:6379).
        password: Redis password.

    Returns:
        Redis client.
    """
    client = Redis.from_url(
        f"rediss://{addr}",
        password=password,
        ssl_cert_reqs=None,
        decode_responses=True
    )
    logging.info(f"Initialized Redis client at {addr}")
    return client

def log_error(message: str):
    """
    Logs an error message.

    Args:
        message: Error message to log.
    """
    logging.error(message)