# worker/codebase_analysis.py
"""
Handles durable codebase analysis jobs from Redis stream.
This replaces the previous detached daemon thread approach.
Ensures codebase analysis failures are observable and retryable.
"""

import logging
import asyncio

from codebase.analyzer import CodebaseAnalyzer
from utils.supabase import init_supabase

logger = logging.getLogger("codebase_analysis")

supabase = init_supabase()
analyzer = CodebaseAnalyzer(supabase)


class CodebaseAnalysisHandler:
    """
    Handles processing of codebase analysis jobs from the Redis stream.
    Processes incremental GitHub push events for file-level entity extraction.
    """

    async def process(self, job: dict, stream: str, msg_id: str, redis_client):
        """
        Process a codebase analysis job from the Redis stream.
        
        Args:
            job: Job dict with record_id, company_id, payload, etc.
            stream: Stream name
            msg_id: Redis message ID
            redis_client: Redis client (not used in async handler, but kept for interface consistency)
        
        Raises:
            Exception: If analysis fails (will prevent ACK in consumer)
        """
        record_id = job.get("record_id")
        company_id = job.get("company_id")
        payload = job.get("payload", {})
        
        if not company_id or company_id.strip() == "default":
            raise ValueError("company_id is required for codebase analysis")
        
        if not record_id:
            raise ValueError("record_id is required for codebase analysis")
        
        logger.info(f"Starting codebase analysis | record={record_id} | company={company_id}")
        
        try:
            # Run the async analysis
            success = await analyzer.process_push_event(
                payload,
                record_id,
                company_id=company_id,
            )
            
            if not success:
                raise RuntimeError(f"Codebase analysis returned false for {record_id}")
            
            logger.info(f"Codebase analysis completed | record={record_id}")
            
        except Exception as e:
            logger.error(f"Codebase analysis failed | record={record_id}: {e}", exc_info=True)
            raise
