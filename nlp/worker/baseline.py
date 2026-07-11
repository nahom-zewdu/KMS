# nlp/worker/baseline.py
"""
Handles baseline synchronization for codebase repositories.
"""

import logging
from codebase.baseline import CodebaseBaselineSync
from utils.supabase import init_supabase

logger = logging.getLogger("baseline")

supabase = init_supabase()
baseline_sync = CodebaseBaselineSync(supabase)

class BaselineHandler:
    """
    Handles processing of baseline synchronization jobs.
    """
    def process(self, job: dict, stream: str, msg_id: str, redis_client):
        repo = job.get("payload", {}).get("repo")
        if not repo:
            logger.error("No repo in baseline job")
            return

        logger.info(f"Starting baseline sync for {repo}")
        # Run synchronously for now (or thread if very large)
        # In production, consider background task queue
        success = baseline_sync.sync_repository(repo)
        
        if success:
            logger.info(f"Baseline sync completed for {repo}")