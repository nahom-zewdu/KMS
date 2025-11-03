# utils/supabase.py
"""
Supabase client with typed initialization and error handling.
"""
import os
from supabase import create_client, Client
from .logger import setup_structured_logging
import logging

def init_supabase() -> Client:
    """
    Initialize Supabase client with service role key.
    Uses environment variables:
        SUPABASE_URL
        SUPABASE_KEY
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
    
    try:
        client = create_client(url, key)
        logging.info("Supabase client initialized")
        return client
    except Exception as e:
        logging.error(f"Failed to initialize Supabase: {e}")
        raise
