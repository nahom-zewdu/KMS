# tests/test_ingestion_reliability.py
"""
Tests for ingestion reliability fixes (Batch 3).

Tests focus on:
1. Baseline failure propagation
2. Codebase analysis as durable Redis job (not daemon)
3. Failure semantics
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from worker.baseline import BaselineHandler
from worker.codebase_analysis import CodebaseAnalysisHandler
from worker.ingestion import IngestionHandler


class TestBaselineFailureSemanticsv2:
    """Baseline failures must propagate and not be silently swallowed."""

    def test_baseline_failure_raises_exception(self):
        """When baseline sync returns False, handler must raise exception."""
        handler = BaselineHandler()
        
        with patch('worker.baseline.baseline_sync') as mock_sync:
            mock_sync.sync_repository.return_value = False
            
            job = {
                "record_id": "test-baseline-123",
                "company_id": "company-abc",
                "payload": {"repo": "org/repo"},
            }
            
            redis_client = Mock()
            
            # Should raise exception when sync fails
            with pytest.raises(RuntimeError, match="Baseline sync failed"):
                handler.process(job, "codebase_baseline_jobs", "msg-1", redis_client)

    def test_baseline_success_returns_normally(self):
        """When baseline sync succeeds, handler completes normally."""
        handler = BaselineHandler()
        
        with patch('worker.baseline.baseline_sync') as mock_sync:
            mock_sync.sync_repository.return_value = True
            
            job = {
                "record_id": "test-baseline-123",
                "company_id": "company-abc",
                "payload": {"repo": "org/repo"},
            }
            
            redis_client = Mock()
            
            # Should complete without raising
            handler.process(job, "codebase_baseline_jobs", "msg-1", redis_client)

    def test_baseline_missing_repo_raises_exception(self):
        """Missing repo in job must raise exception."""
        handler = BaselineHandler()
        
        job = {
            "record_id": "test-baseline-123",
            "company_id": "company-abc",
            "payload": {},  # Missing repo
        }
        
        redis_client = Mock()
        
        with pytest.raises(ValueError, match="repo is required"):
            handler.process(job, "codebase_baseline_jobs", "msg-1", redis_client)

    def test_baseline_missing_company_id_raises_exception(self):
        """Missing company_id must raise exception."""
        handler = BaselineHandler()
        
        job = {
            "record_id": "test-baseline-123",
            "company_id": "",  # Missing/empty
            "payload": {"repo": "org/repo"},
        }
        
        redis_client = Mock()
        
        with pytest.raises(ValueError, match="company_id is required"):
            handler.process(job, "codebase_baseline_jobs", "msg-1", redis_client)


class TestCodebaseAnalysisDurability:
    """Codebase analysis must be published to durable Redis stream, not daemon thread."""

    def test_codebase_analysis_published_to_redis_stream(self):
        """GitHub push events trigger codebase analysis job on Redis stream."""
        handler = IngestionHandler()
        
        job = {
            "record_id": "delivery-123",
            "source": "github",
            "event_type": "push",
            "company_id": "company-abc",
            "payload": {
                "repository": {"full_name": "org/repo"},
                "files": {"added": ["file1.py"], "modified": [], "removed": []},
            },
            "content": "pushed changes",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        with patch('worker.ingestion.supabase') as mock_db, \
             patch('worker.ingestion.redis_client') as mock_redis, \
             patch('worker.ingestion.extract_entities', return_value=[]), \
             patch('worker.ingestion.insert_raw_data'), \
             patch('worker.ingestion.mark_event_processed'):
            
            handler._process_sync(job)
            
            # Verify that xadd was called to publish codebase analysis job
            mock_redis.xadd.assert_called_once()
            call_args = mock_redis.xadd.call_args
            assert call_args[0][0] == "codebase_analysis_jobs"
            
            # Verify the job payload
            payload_dict = json.loads(call_args[0][1]["data"])
            assert payload_dict["RecordID"] == "delivery-123"
            assert payload_dict["CompanyID"] == "company-abc"

    def test_codebase_analysis_not_published_for_non_push_events(self):
        """Non-push GitHub events should NOT trigger codebase analysis."""
        handler = IngestionHandler()
        
        job = {
            "record_id": "delivery-456",
            "source": "github",
            "event_type": "pull_request",  # Not a push
            "company_id": "company-abc",
            "payload": {},
            "content": "some content",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        with patch('worker.ingestion.supabase') as mock_db, \
             patch('worker.ingestion.redis_client') as mock_redis, \
             patch('worker.ingestion.extract_entities', return_value=[]), \
             patch('worker.ingestion.insert_raw_data'), \
             patch('worker.ingestion.mark_event_processed'):
            
            handler._process_sync(job)
            
            # xadd should NOT be called for non-push events
            mock_redis.xadd.assert_not_called()

    def test_codebase_analysis_not_published_for_slack_events(self):
        """Slack events should NOT trigger codebase analysis."""
        handler = IngestionHandler()
        
        job = {
            "record_id": "slack-ts-123",
            "source": "slack",
            "event_type": "message",
            "company_id": "company-abc",
            "payload": {},
            "content": "some content",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        with patch('worker.ingestion.supabase') as mock_db, \
             patch('worker.ingestion.redis_client') as mock_redis, \
             patch('worker.ingestion.extract_entities', return_value=[]), \
             patch('worker.ingestion.insert_raw_data'), \
             patch('worker.ingestion.mark_event_processed'):
            
            handler._process_sync(job)
            
            # xadd should NOT be called for Slack events
            mock_redis.xadd.assert_not_called()


class TestCodebaseAnalysisHandler:
    """CodebaseAnalysisHandler processes analysis jobs from Redis stream."""

    @pytest.mark.asyncio
    async def test_codebase_analysis_success(self):
        """Successful codebase analysis completes normally."""
        handler = CodebaseAnalysisHandler()
        
        job = {
            "record_id": "delivery-123",
            "company_id": "company-abc",
            "payload": {
                "repository": {"full_name": "org/repo"},
                "files": {"added": ["file1.py"], "modified": [], "removed": []},
            },
        }
        
        with patch('worker.codebase_analysis.analyzer') as mock_analyzer:
            mock_analyzer.process_push_event = AsyncMock(return_value=True)
            
            redis_client = Mock()
            
            # Should complete without raising
            await handler.process(job, "codebase_analysis_jobs", "msg-1", redis_client)
            
            # Verify analyzer was called
            mock_analyzer.process_push_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_codebase_analysis_failure_raises_exception(self):
        """Failed codebase analysis raises exception."""
        handler = CodebaseAnalysisHandler()
        
        job = {
            "record_id": "delivery-123",
            "company_id": "company-abc",
            "payload": {
                "repository": {"full_name": "org/repo"},
                "files": {"added": ["file1.py"], "modified": [], "removed": []},
            },
        }
        
        with patch('worker.codebase_analysis.analyzer') as mock_analyzer:
            mock_analyzer.process_push_event = AsyncMock(return_value=False)
            
            redis_client = Mock()
            
            # Should raise exception when analysis returns False
            with pytest.raises(RuntimeError, match="returned false"):
                await handler.process(job, "codebase_analysis_jobs", "msg-1", redis_client)

    @pytest.mark.asyncio
    async def test_codebase_analysis_missing_company_id(self):
        """Missing company_id raises exception."""
        handler = CodebaseAnalysisHandler()
        
        job = {
            "record_id": "delivery-123",
            "company_id": "",  # Missing
            "payload": {},
        }
        
        redis_client = Mock()
        
        with pytest.raises(ValueError, match="company_id is required"):
            await handler.process(job, "codebase_analysis_jobs", "msg-1", redis_client)

    @pytest.mark.asyncio
    async def test_codebase_analysis_exception_propagates(self):
        """Exceptions during analysis propagate."""
        handler = CodebaseAnalysisHandler()
        
        job = {
            "record_id": "delivery-123",
            "company_id": "company-abc",
            "payload": {},
        }
        
        with patch('worker.codebase_analysis.analyzer') as mock_analyzer:
            mock_analyzer.process_push_event = AsyncMock(
                side_effect=RuntimeError("Network error")
            )
            
            redis_client = Mock()
            
            with pytest.raises(RuntimeError, match="Network error"):
                await handler.process(job, "codebase_analysis_jobs", "msg-1", redis_client)
