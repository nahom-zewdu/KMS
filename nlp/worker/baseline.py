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
        company_id = (job.get("company_id") or job.get("payload", {}).get("company_id") or "").strip()
        if not company_id or company_id.lower() == "default":
            raise ValueError("a real company_id is required for baseline sync")
        if not repo:
            logger.error("No repo in baseline job")
            raise ValueError("repo is required for baseline sync")
        record_id = job.get("record_id") or "unknown"
        logger.info(
            "Starting baseline sync | stream=%s | message_id=%s | "
            "record_id=%s | repo=%s | company=%s",
            stream,
            msg_id,
            record_id,
            repo,
            company_id,
        )
        success = baseline_sync.sync_repository(repo, company_id=company_id)
        if not success:
            raise RuntimeError(f"Baseline sync failed for {repo}")
        logger.info(
            "Baseline sync completed | stream=%s | message_id=%s | "
            "record_id=%s | repo=%s",
            stream,
            msg_id,
            record_id,
            repo,
        )