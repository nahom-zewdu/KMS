"""Opt-in end-to-end routing checks against the configured KMS Supabase project.

Run against the development/test project only:
  KMS_RETRIEVAL_ROUTER_SUPABASE_INTEGRATION=1 uv run pytest -q tests/test_retrieval_router_supabase_integration.py

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. Fixtures use generated
repository/snapshot IDs and cleanup only repositories created by this test.
"""
from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    os.getenv("KMS_RETRIEVAL_ROUTER_SUPABASE_INTEGRATION") != "1",
    reason="set KMS_RETRIEVAL_ROUTER_SUPABASE_INTEGRATION=1 for the configured dev/test project",
)


def test_router_respects_active_snapshot_scope_and_scip_fallback(tmp_path: Path):
    url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_role_key:
        pytest.skip("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    from supabase import create_client

    from codebase.scip_indexer import normalize_scip_index
    from codebase.scip_occurrence_indexer import ScipOccurrenceIndexer
    from codebase.source_chunk_indexer import SourceChunkIndexer
    from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever
    from codebase.source_chunk_retriever import SourceChunkRetriever
    from query_engine.code_lexical import CodeLexicalRetriever
    from query_engine.retrieval_router import (
        RetrievalRequest,
        RetrievalTask,
        TaskAwareRetrievalRouter,
    )

    client = create_client(url, service_role_key)
    suffix = uuid.uuid4().hex
    company_id = f"kms-router-it-{suffix}"
    repository_id = str(uuid.uuid4())
    snapshot_a = str(uuid.uuid4())
    snapshot_b = str(uuid.uuid4())
    revision_a = f"router-revision-{suffix}-a"
    revision_b = f"router-revision-{suffix}-b"
    fixtures_root = tmp_path / "scip-fixture"
    source_root = fixtures_root / "src"
    source_root.mkdir(parents=True)
    file_path = "src/payment.py"

    source_a = (
        "def authorize_payment(amount):\n"
        "    return amount > 0\n"
        "\n"
        "def checkout(amount):\n"
        "    return authorize_payment(amount)\n"
    )
    source_b = (
        "def reconcile_payment(amount):\n"
        "    return amount >= 0\n"
    )
    (fixtures_root / file_path).write_text(source_a, encoding="utf-8")

    created_repository = False
    try:
        client.table("repositories").insert({
            "id": repository_id,
            "company_id": company_id,
            "full_name": f"kms-integration/{suffix}",
            "default_branch": "main",
            "baseline_status": "indexing",
        }).execute()
        created_repository = True

        def create_snapshot(snapshot_id: str, revision: str) -> None:
            client.table("repository_snapshots").insert({
                "id": snapshot_id,
                "repository_id": repository_id,
                "company_id": company_id,
                "source_revision": revision,
                "run_id": str(uuid.uuid4()),
                "status": "building",
                "validation": {},
            }).execute()
            client.table("codebase_files").insert({
                "repository_id": repository_id,
                "file_path": file_path,
                "file_name": "payment.py",
                "company_id": company_id,
                "snapshot_id": snapshot_id,
                "language": "python",
                "last_commit_sha": revision,
            }).execute()

        create_snapshot(snapshot_a, revision_a)
        client.table("repositories").update({
            "active_snapshot_id": snapshot_a,
        }).eq("id", repository_id).eq("company_id", company_id).execute()

        chunks = SourceChunkIndexer(client)
        indexed_a = chunks.index_file(
            repository_id=repository_id,
            snapshot_id=snapshot_a,
            company_id=company_id,
            file_path=file_path,
            source=source_a,
            source_revision=revision_a,
        )
        assert indexed_a["status"] == "indexed"
        assert indexed_a["chunks_persisted"] > 0

        symbol = "scip-python python kms-fixture Payment.authorize_payment()."
        index_data = {
            "metadata": {
                "version": 1,
                "projectRoot": fixtures_root.as_uri(),
                "toolInfo": {"name": "router-integration", "version": "1.0"},
                "textDocumentEncoding": 1,
            },
            "documents": [{
                "relativePath": file_path,
                "positionEncoding": 1,
                "occurrences": [
                    {"range": [0, 4, 0, 21], "symbol": symbol, "symbolRoles": 1},
                    {"range": [4, 11, 4, 28], "symbol": symbol, "symbolRoles": 8},
                ],
            }],
        }
        scip_index = normalize_scip_index(
            index_data,
            repository_root=fixtures_root,
            source_revision=revision_a,
        )
        persisted = ScipOccurrenceIndexer(client).persist(
            scip_index,
            repository_id=repository_id,
            snapshot_id=snapshot_a,
            company_id=company_id,
            source_revision=revision_a,
        )
        assert persisted["references"] == 1

        router = TaskAwareRetrievalRouter(
            declarations=CodeLexicalRetriever(client),
            occurrences=ScipOccurrenceRetriever(client),
            passages=SourceChunkRetriever(client),
        )

        call_site = router.retrieve(RetrievalRequest(
            task=RetrievalTask.CALL_SITE_NAVIGATION,
            company_id=company_id,
            repository_id=repository_id,
            scip_symbol=symbol,
            terms=("authorize_payment",),
        ))
        assert call_site.strategy == "scip-references"
        assert len(call_site.candidates) == 1
        occurrence = call_site.candidates[0]
        assert occurrence.company_id == company_id
        assert occurrence.repository_id == repository_id
        assert occurrence.snapshot_id == snapshot_a
        assert occurrence.source_revision == revision_a
        assert occurrence.file_path == file_path
        assert occurrence.metadata["role"] == "reference"

        passage = router.retrieve(RetrievalRequest(
            task=RetrievalTask.PASSAGE_RETRIEVAL,
            company_id=company_id,
            repository_id=repository_id,
            terms=("authorize_payment",),
        ))
        assert passage.candidates
        assert all(item.snapshot_id == snapshot_a for item in passage.candidates)

        # A different tenant cannot use this repository's identifier.
        cross_tenant = router.retrieve(RetrievalRequest(
            task=RetrievalTask.PASSAGE_RETRIEVAL,
            company_id=f"other-{suffix}",
            repository_id=repository_id,
            terms=("authorize_payment",),
        ))
        assert cross_tenant.candidates == ()

        # Publish a second active pointer with unrelated source. The old SCIP
        # occurrence and old source chunk must no longer be visible to routing.
        create_snapshot(snapshot_b, revision_b)
        indexed_b = chunks.index_file(
            repository_id=repository_id,
            snapshot_id=snapshot_b,
            company_id=company_id,
            file_path=file_path,
            source=source_b,
            source_revision=revision_b,
        )
        assert indexed_b["status"] == "indexed"
        client.table("repositories").update({
            "active_snapshot_id": snapshot_b,
        }).eq("id", repository_id).eq("company_id", company_id).execute()

        historical_call = router.retrieve(RetrievalRequest(
            task=RetrievalTask.CALL_SITE_NAVIGATION,
            company_id=company_id,
            repository_id=repository_id,
            scip_symbol=symbol,
            terms=("authorize_payment",),
        ))
        assert historical_call.strategy == "source-chunk-lexical-fallback"
        assert historical_call.fallback_reason == "no_active_snapshot_references_for_exact_scip_symbol"
        assert historical_call.candidates == ()

        historical_passage = router.retrieve(RetrievalRequest(
            task=RetrievalTask.PASSAGE_RETRIEVAL,
            company_id=company_id,
            repository_id=repository_id,
            terms=("authorize_payment",),
        ))
        assert historical_passage.candidates == ()

    finally:
        if created_repository:
            client.table("repositories").delete().eq("id", repository_id).eq(
                "company_id", company_id
            ).execute()
