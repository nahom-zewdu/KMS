"""Legacy GitHub push stream compatibility handler.

New pushes are sent directly to the baseline queue. Messages already present in
codebase_analysis_jobs are converted into a full immutable baseline sync instead
of mutating the currently published inventory incrementally.
"""

import logging

from codebase.baseline import CodebaseBaselineSync
from utils.supabase import init_supabase
from utils.db_helpers import ensure_event_tenant

logger = logging.getLogger("codebase_analysis")

supabase = init_supabase()
baseline_sync = CodebaseBaselineSync(supabase)


class CodebaseAnalysisHandler:
    async def process(self, job: dict, stream: str, msg_id: str, redis_client):
        record_id = job.get("record_id")
        company_id = (job.get("company_id") or "").strip()
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}

        if not company_id or company_id.lower() == "default":
            raise ValueError("company_id is required for codebase analysis")
        if not record_id:
            raise ValueError("record_id is required for codebase analysis")

        ensure_event_tenant(supabase, record_id, company_id)

        repository = payload.get("repository")
        repo_name = (
            repository.get("full_name")
            if isinstance(repository, dict)
            else None
        ) or payload.get("repo")
        if not isinstance(repo_name, str) or not repo_name.strip():
            raise ValueError("GitHub push payload does not contain repository.full_name")

        logger.info(
            "Converting legacy push analysis into snapshot baseline sync | repo=%s | company=%s",
            repo_name, company_id,
        )
        if not baseline_sync.sync_repository(repo_name.strip(), company_id):
            raise RuntimeError(f"Snapshot baseline sync failed for {repo_name}")
