"""Opt-in integration tests against the configured KMS Supabase project.

Run only against the development/test project:
  KMS_SUPABASE_INTEGRATION=1 uv run pytest tests/test_source_chunk_supabase_integration.py -q

Required environment:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

The test creates uniquely named tenant/repository/snapshot fixtures and deletes
only the two repositories it created. Repository cascades remove their snapshots,
source files, and source chunks.
"""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    os.getenv("KMS_SUPABASE_INTEGRATION") != "1",
    reason="set KMS_SUPABASE_INTEGRATION=1 to run against the configured Supabase project",
)


def test_source_chunk_indexer_and_retriever_against_supabase():
    url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_role_key:
        pytest.skip("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    from supabase import create_client

    from codebase.source_chunk_indexer import SourceChunkIndexer
    from codebase.source_chunk_retriever import SourceChunkRetriever

    client = create_client(url, service_role_key)
    suffix = uuid.uuid4().hex
    fixtures: list[tuple[str, str, str, str, str]] = []

    def create_fixture(label: str) -> tuple[str, str, str, str, str]:
        company_id = f"kms-krt03-it-{suffix}-{label}"
        repository_id = str(uuid.uuid4())
        snapshot_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        revision = f"fixture-revision-{suffix}-{label}"
        full_name = f"kms-integration/{suffix}-{label}"

        client.table("repositories").insert({
            "id": repository_id,
            "company_id": company_id,
            "full_name": full_name,
            "default_branch": "main",
            "baseline_status": "indexing",
        }).execute()

        client.table("repository_snapshots").insert({
            "id": snapshot_id,
            "repository_id": repository_id,
            "company_id": company_id,
            "source_revision": revision,
            "run_id": run_id,
            "status": "building",
            "validation": {},
        }).execute()

        client.table("codebase_files").insert({
            "repository_id": repository_id,
            "file_path": "src/integration_probe.py",
            "file_name": "integration_probe.py",
            "company_id": company_id,
            "snapshot_id": snapshot_id,
            "language": "python",
            "last_commit_sha": revision,
        }).execute()

        client.table("repositories").update({
            "active_snapshot_id": snapshot_id,
        }).eq("id", repository_id).eq("company_id", company_id).execute()

        fixture = (company_id, repository_id, snapshot_id, revision, full_name)
        fixtures.append(fixture)
        return fixture

    try:
        tenant_a = create_fixture("alpha")
        tenant_b = create_fixture("beta")

        company_a, repo_a, snapshot_a, revision_a, _ = tenant_a
        company_b, repo_b, snapshot_b, revision_b, _ = tenant_b

        indexer = SourceChunkIndexer(client, batch_size=2)
        source_a = (
            "def calculate_invoice_total(items):\n"
            "    subtotal = sum(item.amount for item in items)\n"
            "    return subtotal\n"
        )
        source_b = (
            "def calculate_shipping_distance(points):\n"
            "    return sum(point.distance for point in points)\n"
        )

        result_a = indexer.index_file(
            repository_id=repo_a,
            snapshot_id=snapshot_a,
            company_id=company_a,
            file_path="src/integration_probe.py",
            source=source_a,
            source_revision=revision_a,
        )
        assert result_a["status"] == "indexed"
        assert result_a["chunks_persisted"] > 0

        # Repeating the same ingestion must upsert, not duplicate.
        repeated_a = indexer.index_file(
            repository_id=repo_a,
            snapshot_id=snapshot_a,
            company_id=company_a,
            file_path="src/integration_probe.py",
            source=source_a,
            source_revision=revision_a,
        )
        assert repeated_a["chunks_persisted"] == result_a["chunks_persisted"]

        result_b = indexer.index_file(
            repository_id=repo_b,
            snapshot_id=snapshot_b,
            company_id=company_b,
            file_path="src/integration_probe.py",
            source=source_b,
            source_revision=revision_b,
        )
        assert result_b["status"] == "indexed"
        assert result_b["chunks_persisted"] > 0

        rows_a = (
            client.table("source_code_chunks")
            .select("chunk_id")
            .eq("company_id", company_a)
            .eq("repository_id", repo_a)
            .eq("snapshot_id", snapshot_a)
            .execute()
            .data
        )
        assert len(rows_a) == result_a["chunks_persisted"]

        retriever = SourceChunkRetriever(client)
        retrieved_a = retriever.retrieve(
            company_id=company_a,
            repository_id=repo_a,
            terms=["calculate_invoice_total"],
        )
        assert retrieved_a
        assert all(item.company_id == company_a for item in retrieved_a)
        assert all(item.repository_id == repo_a for item in retrieved_a)
        assert all(item.snapshot_id == snapshot_a for item in retrieved_a)
        assert all(item.source_revision == revision_a for item in retrieved_a)
        assert all(item.file_path == "src/integration_probe.py" for item in retrieved_a)

        # The repository/company pair is checked before querying chunks.
        assert retriever.retrieve(
            company_id=company_b,
            repository_id=repo_a,
            terms=["calculate_invoice_total"],
        ) == []

        retrieved_b = retriever.retrieve(
            company_id=company_b,
            repository_id=repo_b,
            terms=["calculate_shipping_distance"],
        )
        assert retrieved_b
        assert all(item.company_id == company_b for item in retrieved_b)
        assert all(item.repository_id == repo_b for item in retrieved_b)
        assert all(item.snapshot_id == snapshot_b for item in retrieved_b)
        assert not any(item.company_id == company_a for item in retrieved_b)

    finally:
        # Delete only fixture repositories by their generated UUIDs.
        for _, repository_id, _, _, _ in reversed(fixtures):
            client.table("repositories").delete().eq("id", repository_id).execute()
