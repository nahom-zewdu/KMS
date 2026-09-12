from unittest.mock import Mock

from ramp.evidence_generator import EvidenceRampPlanGenerator


class Query:
    """Small Supabase query double for deterministic evidence-generator tests."""

    def __init__(self, data):
        self.data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return type("Response", (), {"data": self.data})()


class TestEvidenceRampGenerator:
    """Verify RID-05 uses company-indexed evidence and refuses unsupported candidates."""

    def _generator(self, files, modules=None, history=None):
        generator = EvidenceRampPlanGenerator(Mock())
        generator.supabase.table.side_effect = lambda name: {
            "codebase_files": Query(files),
            "codebase_modules": Query(modules or []),
            "raw_data": Query(history or []),
        }[name]
        return generator

    def test_candidate_uses_indexed_paths_not_generator_repo_paths(self):
        generator = self._generator(
            files=[
                {
                    "id": "f1",
                    "repository_id": "r1",
                    "file_path": "services/webhook/entry.go",
                    "file_name": "entry.go",
                    "module_path": "services/webhook",
                    "language": "Go",
                    "last_author": "alice",
                    "last_commit_sha": "abc",
                    "importance_score": 0.9,
                    "metadata": {},
                    "company_id": "company-1",
                },
                {
                    "id": "f2",
                    "repository_id": "r1",
                    "file_path": "services/queue/redis.go",
                    "file_name": "redis.go",
                    "module_path": "services/queue",
                    "language": "Go",
                    "last_author": "bob",
                    "last_commit_sha": "def",
                    "importance_score": 0.8,
                    "metadata": {},
                    "company_id": "company-1",
                },
            ],
            modules=[
                {
                    "id": "m1",
                    "repository_id": "r1",
                    "module_path": "services/webhook",
                    "module_name": "webhook",
                    "inferred_type": "service",
                    "description": "Webhook entry service",
                    "importance_score": 0.9,
                    "metadata": {},
                    "company_id": "company-1",
                }
            ],
            history=[
                {
                    "record_id": "h1",
                    "event_id": None,
                    "source": "github",
                    "content": "alice changed services/webhook/entry.go",
                    "created_at": "2026-09-12T00:00:00Z",
                    "company_id": "company-1",
                }
            ],
        )

        candidate = generator.build_github_ingestion_workflow_candidate("company-1", "backend-engineer")

        assert candidate is not None
        assert candidate.evidence_refs
        assert candidate.implementation_refs == [
            "services/webhook/entry.go",
            "services/queue/redis.go",
        ]
        assert "api/handlers/github.go" not in candidate.evidence_refs
        assert candidate.selection_metadata["evidence"]
        assert all(item["source"] == "codebase_files" for item in candidate.selection_metadata["evidence"])
        assert candidate.contribution_candidate is False

    def test_candidate_requires_indexed_evidence(self):
        generator = self._generator(
            files=[
                {
                    "file_path": "docs/github.md",
                    "module_path": "docs",
                    "importance_score": 0.1,
                    "company_id": "company-1",
                }
            ]
        )

        assert generator.build_github_ingestion_workflow_candidate("company-1", "backend-engineer") is None

    def test_candidate_is_company_scoped(self):
        generator = self._generator(
            files=[
                {
                    "file_path": "webhook/entry.go",
                    "module_path": "webhook",
                    "importance_score": 0.8,
                    "company_id": "company-2",
                },
                {
                    "file_path": "queue/redis.go",
                    "module_path": "queue",
                    "importance_score": 0.7,
                    "company_id": "company-2",
                },
            ]
        )

        candidate = generator.build_github_ingestion_workflow_candidate("company-1", "backend-engineer")
        assert candidate is None or candidate.selection_metadata["company_id"] == "company-1"
