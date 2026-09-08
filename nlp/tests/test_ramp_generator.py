import uuid
from unittest.mock import Mock

from ramp.generator import RampPlanGenerator


class TestRampGeneratorQuality:
    def setup_method(self):
        self.generator = RampPlanGenerator(supabase=Mock())

    def _build_steps(self, modules, key_files=None, owner_index=None, architecture=None):
        return self.generator._build_steps(
            role="backend",
            company_id="company-123",
            modules=modules,
            key_files=key_files or [],
            owner_index=owner_index or {},
            safe_paths=set(),
            risk_paths=set(),
            architecture=architecture or [{"name": "API Layer", "description": "API services"}],
        )

    def test_evidence_backed_why_generation(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "handlers",
                    "path": "api/handlers",
                    "description": "HTTP request handling for the backend API.",
                    "importance": 0.9,
                    "file_count": 4,
                }
            ],
            key_files=[
                {"path": "api/handlers/tenant.py", "module": "api/handlers", "last_author": "alice"},
                {"path": "api/handlers/routes.py", "module": "api/handlers", "last_author": "bob"},
            ],
            owner_index={"api/handlers": ["alice"]},
        )

        step = steps[0]
        why = step["why"]
        assert "api/handlers" in why
        assert "this repo" in why.lower() or "specific" in why.lower()
        assert "owner" in why.lower() or "evidence" in why.lower()
        assert any(ev.get("kind") == "observed" for ev in step["evidence"])

    def test_context_generation_is_specific_and_understandable(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "handlers",
                    "path": "api/handlers",
                    "description": "HTTP request handling for the backend API.",
                    "importance": 0.9,
                    "file_count": 3,
                }
            ],
            key_files=[{"path": "api/handlers/tenant.py", "module": "api/handlers"}],
            owner_index={"api/handlers": ["alice"]},
            architecture=[{"name": "API Layer", "description": "API services"}],
        )

        step = steps[0]
        assert "understand" in step
        assert "api/handlers" in step["understand"]
        assert "HTTP" in step["understand"] or "request" in step["understand"].lower()
        assert step["summary"]["what"]
        assert step["summary"]["where"]

    def test_weak_evidence_does_not_fabricate_claims(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "mystery",
                    "path": "ops/unknown",
                    "description": "",
                    "importance": 0.2,
                    "file_count": 0,
                }
            ],
            key_files=[],
            owner_index={},
        )

        step = steps[0]
        why = step["why"].lower()
        assert "uncertain" in why or "limited" in why or "not enough" in why
        assert "ops/unknown" in step["understand"] or "ops/unknown" in step["summary"]["what"]
        assert any(ev.get("kind") == "inference" for ev in step["evidence"])

    def test_human_readable_evidence_mapping(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "handlers",
                    "path": "api/handlers",
                    "description": "HTTP request handling for the backend API.",
                    "importance": 0.8,
                    "file_count": 2,
                }
            ],
            key_files=[{"path": "api/handlers/routes.py", "module": "api/handlers"}],
            owner_index={"api/handlers": ["alice"]},
        )

        step = steps[0]
        evidence = step["evidence"]
        assert evidence
        assert all("kind" in ev for ev in evidence)
        assert any(ev.get("kind") == "observed" for ev in evidence)
        assert any(ev.get("source") for ev in evidence)

    def test_step_has_concrete_do_and_done_when(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "handlers",
                    "path": "api/handlers",
                    "description": "HTTP request handling for the backend API.",
                    "importance": 0.9,
                    "file_count": 3,
                }
            ],
            key_files=[
                {"path": "api/handlers/routes.py", "module": "api/handlers"},
                {"path": "api/handlers/tenant.py", "module": "api/handlers"},
            ],
            owner_index={"api/handlers": ["alice"]},
        )

        step = steps[0]
        assert "do" in step
        assert "done_when" in step
        assert "api/handlers" in step["do"]
        assert "inspect" in step["do"].lower() or "trace" in step["do"].lower()
        assert "explain" in step["done_when"].lower() or "identify" in step["done_when"].lower()
        assert "repository" in step["done_when"].lower() or "code" in step["done_when"].lower()


    def test_role_relevance_and_weak_evidence_are_guarded(self):
        steps = self._build_steps(
            modules=[
                {
                    "name": "components",
                    "path": "app/components",
                    "description": "",
                    "importance": 0.4,
                    "file_count": 0,
                }
            ],
            key_files=[],
            owner_index={},
            architecture=[{"name": "Frontend Layer", "description": "UI components"}],
        )

        step = steps[0]
        do_text = step["do"].lower()
        done_text = step["done_when"].lower()
        assert "frontend" in do_text or "component" in do_text
        assert "limited" in step["why"].lower() or "uncertain" in step["why"].lower() or "not enough" in step["why"].lower()
        assert "confirmed" not in step["why"].lower() or "not enough" in step["why"].lower()
        assert "can explain" in done_text or "identify" in done_text

    def test_step_ids_remain_stable(self):
        steps = self._build_steps(
            modules=[
                {"name": "handlers", "path": "api/handlers", "description": "HTTP request handling for the backend API.", "importance": 0.9, "file_count": 2},
                {"name": "repository", "path": "api/repository", "description": "Repo storage wrappers.", "importance": 0.8, "file_count": 2},
            ],
            key_files=[
                {"path": "api/handlers/routes.py", "module": "api/handlers"},
                {"path": "api/repository/supabase.py", "module": "api/repository"},
            ],
            owner_index={"api/handlers": ["alice"], "api/repository": ["bob"]},
        )

        expected_first = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "ramp-step:company-123:backend:api/handlers:1",
            )
        )
        assert steps[0]["id"] == expected_first
        assert [step["order"] for step in steps] == [1, 2]

    def test_valid_repository_file_resolution(self):
        class Query:
            def __init__(self, data):
                self.data = data

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def in_(self, *_args, **_kwargs):
                return self

            def execute(self):
                return type("Resp", (), {"data": self.data})()

        repo_rows = [{"id": "repo-1", "full_name": "acme/backend", "default_branch": "main"}]
        file_rows = [{"repository_id": "repo-1", "file_path": "api/handlers/routes.py", "module_path": "api/handlers"}]

        self.generator.supabase = Mock()
        self.generator.supabase.table.side_effect = lambda name: {
            "codebase_files": Query(file_rows),
            "repositories": Query(repo_rows),
        }[name]

        result = self.generator._resolve_target_reference("company-123", "api/handlers", [{"path": "api/handlers/routes.py"}])

        assert result["repo"]["full_name"] == "acme/backend"
        assert result["repo"]["github_url"] == "https://github.com/acme/backend/tree/main/api/handlers"
        assert result["files"][0]["path"] == "api/handlers/routes.py"
        assert result["files"][0]["github_url"] == "https://github.com/acme/backend/blob/main/api/handlers/routes.py"

    def test_missing_repository_is_handled_gracefully(self):
        class Query:
            def __init__(self, data):
                self.data = data

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def in_(self, *_args, **_kwargs):
                return self

            def execute(self):
                return type("Resp", (), {"data": self.data})()

        self.generator.supabase = Mock()
        self.generator.supabase.table.side_effect = lambda name: {
            "codebase_files": Query([]),
            "repositories": Query([]),
        }[name]

        result = self.generator._resolve_target_reference("company-123", "api/handlers", [])

        assert result["repo"] is None
        assert result["files"] == []
        assert result["github_url"] is None

    def test_missing_file_and_malformed_resource_data_are_ignored(self):
        class Query:
            def __init__(self, data):
                self.data = data

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def in_(self, *_args, **_kwargs):
                return self

            def execute(self):
                return type("Resp", (), {"data": self.data})()

        self.generator.supabase = Mock()
        self.generator.supabase.table.side_effect = lambda name: {
            "codebase_files": Query([{"repository_id": "repo-1", "file_path": None, "module_path": None}]),
            "repositories": Query([{"id": "repo-1", "full_name": "acme/backend", "default_branch": "main"}]),
        }[name]

        result = self.generator._resolve_target_reference("company-123", "", [{"path": 123, "module": 456}])
        assert result["repo"]["full_name"] == "acme/backend"
        assert result["files"] == []

    def test_company_scoped_resolution_ignores_other_company_records(self):
        class Query:
            def __init__(self, data):
                self.data = data

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def in_(self, *_args, **_kwargs):
                return self

            def execute(self):
                return type("Resp", (), {"data": self.data})()

        self.generator.supabase = Mock()
        self.generator.supabase.table.side_effect = lambda name: {
            "codebase_files": Query([
                {"repository_id": "repo-1", "company_id": "company-123", "file_path": "api/handlers/routes.py", "module_path": "api/handlers"},
                {"repository_id": "repo-2", "company_id": "company-999", "file_path": "api/other.py", "module_path": "api/other"},
            ]),
            "repositories": Query([
                {"id": "repo-1", "company_id": "company-123", "full_name": "acme/backend", "default_branch": "main"},
                {"id": "repo-2", "company_id": "company-999", "full_name": "other/project", "default_branch": "main"},
            ]),
        }[name]

        result = self.generator._resolve_target_reference("company-123", "api/handlers", [{"path": "api/handlers/routes.py"}])
        assert result["repo"]["full_name"] == "acme/backend"
        assert result["repo"]["company_id"] == "company-123"
        assert "other/project" not in result["repo"]["github_url"]

    def test_no_fabricated_links_for_malformed_repo_data(self):
        class Query:
            def __init__(self, data):
                self.data = data

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def in_(self, *_args, **_kwargs):
                return self

            def execute(self):
                return type("Resp", (), {"data": self.data})()

        self.generator.supabase = Mock()
        self.generator.supabase.table.side_effect = lambda name: {
            "codebase_files": Query([{"repository_id": "repo-1", "file_path": "api/handlers/routes.py", "module_path": "api/handlers"}]),
            "repositories": Query([{"id": "repo-1", "full_name": "", "default_branch": ""}]),
        }[name]

        result = self.generator._resolve_target_reference("company-123", "api/handlers", [{"path": "api/handlers/routes.py"}])
        assert result["repo"] is None
        assert result["files"][0]["github_url"] is None


class TestRampStepProgress:
    def setup_method(self):
        self.generator = RampPlanGenerator(supabase=Mock())

    def test_valid_transition_to_in_progress(self):
        self.generator.supabase = self._memory_supabase()
        result = self.generator.update_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
            status="in_progress",
        )
        assert result["status"] == "in_progress"
        assert result["step_id"] == "step-1"
