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
        """ Process a baseline sync job from the Redis stream."""
        repo = job.get("payload", {}).get("repo")
        company_id = job.get("company_id") or job.get("payload", {}).get("company_id") or ""
        if not company_id:
            raise ValueError("company_id is required for baseline sync")
        if not repo:
            logger.error("No repo in baseline job")
            return
        logger.info(f"Starting baseline sync for {repo} | company={company_id}")
        success = baseline_sync.sync_repository(repo, company_id=company_id)
        if success:
            logger.info(f"Baseline sync completed for {repo}")