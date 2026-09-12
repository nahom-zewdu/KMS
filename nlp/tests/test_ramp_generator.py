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


class TestWorkflowCandidates:
    def setup_method(self):
        self.generator = RampPlanGenerator(supabase=Mock())

    def test_workflow_candidate_construction_uses_real_github_integration_evidence(self):
        candidate = self.generator.build_github_ingestion_workflow_candidate(company_id="company-123", role="backend")

        assert candidate.candidate_type == "workflow-learning"
        assert "GitHub webhook" in candidate.objective
        assert "api/handlers/github.go" in candidate.implementation_refs
        assert "api/services/github.go" in candidate.implementation_refs
        assert "api/services/core.go" in candidate.implementation_refs
        assert candidate.concrete_action
        assert candidate.verification_method
        assert candidate.evidence_refs

    def test_learning_eligibility_rejects_missing_company_scope_or_evidence(self):
        ineligible = self.generator._build_learning_candidate(
            candidate_id="candidate-missing-company",
            candidate_type="workflow-learning",
            stage="learning",
            objective="Trace an event through the system.",
            evidence_refs=["api/handlers/github.go"],
            implementation_refs=["api/handlers/github.go"],
            workflow_refs=["webhook→handler"],
            role_relevance=0.5,
            evidence_strength=0.8,
            prerequisite_value=0.5,
            workflow_value=0.6,
            actionability=0.7,
            verification_strength=0.8,
            help_available=0.5,
            prerequisites=[],
            selection_reason="Missing company scope.",
            company_scoped=False,
            concrete_action="Inspect the GitHub webhook flow.",
            verification_method="Read the handler and confirm the call path.",
        )
        assert self.generator.is_learning_eligible(ineligible) is False

        missing_impl = self.generator._build_learning_candidate(
            candidate_id="candidate-missing-impl",
            candidate_type="workflow-learning",
            stage="learning",
            objective="Trace an event through the system.",
            evidence_refs=["api/handlers/github.go"],
            implementation_refs=[],
            workflow_refs=[],
            role_relevance=0.5,
            evidence_strength=0.8,
            prerequisite_value=0.5,
            workflow_value=0.6,
            actionability=0.7,
            verification_strength=0.8,
            help_available=0.5,
            prerequisites=[],
            selection_reason="Missing implementation evidence.",
            company_scoped=True,
            concrete_action="Inspect the GitHub webhook flow.",
            verification_method="Read the handler and confirm the call path.",
        )
        assert self.generator.is_learning_eligible(missing_impl) is False

        eligible = self.generator._build_learning_candidate(
            candidate_id="candidate-eligible",
            candidate_type="workflow-learning",
            stage="learning",
            objective="Trace one GitHub event from webhook entry through validation, persistence, and queue publication.",
            evidence_refs=["api/handlers/github.go", "api/services/github.go", "api/services/core.go"],
            implementation_refs=["api/handlers/github.go", "api/services/github.go", "api/services/core.go"],
            workflow_refs=["GitHub webhook", "validation", "ingestion", "events persistence", "raw_data persistence", "github_jobs"],
            role_relevance=1.0,
            evidence_strength=1.0,
            prerequisite_value=0.8,
            workflow_value=0.9,
            actionability=0.9,
            verification_strength=0.8,
            help_available=0.7,
            prerequisites=["understand ingestion boundary"],
            selection_reason="Direct backend evidence proves the workflow.",
            company_scoped=True,
            concrete_action="Trace the handler->service->core flow and explain where the event is validated and queued.",
            verification_method="Verify the actual request signature, event type checks, and Redis publication path in code.",
        )
        assert self.generator.is_learning_eligible(eligible) is True


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

    def test_valid_transition_to_completed(self):
        self.generator.supabase = self._memory_supabase()
        self.generator.update_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
            status="in_progress",
        )
        result = self.generator.update_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
            status="completed",
        )
        assert result["status"] == "completed"

    def test_invalid_status_rejected(self):
        self.generator.supabase = self._memory_supabase()
        try:
            self.generator.update_step_progress(
                plan_id="plan-123",
                step_id="step-1",
                company_id="company-123",
                user_id="user-1",
                status="blocked",
            )
            raise AssertionError("Expected ValueError for invalid status")
        except ValueError as exc:
            assert "status" in str(exc).lower()

    def test_nonexistent_step_rejected(self):
        self.generator.supabase = self._memory_supabase()
        try:
            self.generator.update_step_progress(
                plan_id="plan-123",
                step_id="step-nope",
                company_id="company-123",
                user_id="user-1",
                status="completed",
            )
            raise AssertionError("Expected KeyError for missing step")
        except KeyError:
            pass

    def test_wrong_company_rejected(self):
        self.generator.supabase = self._memory_supabase()
        try:
            self.generator.update_step_progress(
                plan_id="plan-123",
                step_id="step-1",
                company_id="company-999",
                user_id="user-1",
                status="completed",
            )
            raise AssertionError("Expected ValueError for wrong company")
        except ValueError:
            pass

    def test_persisted_state_can_be_read_back(self):
        self.generator.supabase = self._memory_supabase()
        self.generator.update_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
            status="completed",
        )
        progress = self.generator.get_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
        )
        assert progress["status"] == "completed"

    def test_repeated_update_is_idempotent(self):
        self.generator.supabase = self._memory_supabase()
        first = self.generator.update_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
            status="in_progress",
        )
        second = self.generator.update_step_progress(
            plan_id="plan-123",
            step_id="step-1",
            company_id="company-123",
            user_id="user-1",
            status="in_progress",
        )
        assert first["status"] == "in_progress"
        assert second["status"] == "in_progress"
        assert first["id"] == second["id"]

    def test_get_active_hydrates_existing_progress_for_matching_step(self):
        self.generator.supabase = Mock()
        self.generator.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
            "id": "plan-123",
            "company_id": "company-123",
            "role": "backend",
            "employee_name": "Ada",
            "title": "First 7 Days — backend",
            "steps": [{"id": "step-1", "order": 1}, {"id": "step-2", "order": 2}],
            "meta": {"source": "ramp_v1"},
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }]
        self.generator.get_progress_for_plan = Mock(return_value={
            "step-1": {"id": "progress-1", "plan_id": "plan-123", "company_id": "company-123", "step_id": "step-1", "user_id": "user-1", "status": "in_progress"},
            "step-2": {"id": "progress-2", "plan_id": "plan-123", "company_id": "company-123", "step_id": "step-2", "user_id": "user-1", "status": "completed"},
        })

        plan = self.generator.get_active(company_id="company-123", role="backend", user_id="user-1")

        assert plan["progress"]["step-1"]["status"] == "in_progress"
        assert plan["steps"][0]["status"] == "in_progress"
        assert plan["steps"][0]["progress"]["status"] == "in_progress"
        assert plan["steps"][1]["status"] == "completed"

    def test_get_active_defaults_missing_step_progress_to_not_started(self):
        self.generator.supabase = Mock()
        self.generator.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
            "id": "plan-123",
            "company_id": "company-123",
            "role": "backend",
            "employee_name": "Ada",
            "title": "First 7 Days — backend",
            "steps": [{"id": "step-1", "order": 1}, {"id": "step-2", "order": 2}, {"id": "step-3", "order": 3}],
            "meta": {"source": "ramp_v1"},
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }]
        self.generator.get_progress_for_plan = Mock(return_value={
            "step-2": {"id": "progress-2", "plan_id": "plan-123", "company_id": "company-123", "step_id": "step-2", "user_id": "user-1", "status": "completed"},
        })

        plan = self.generator.get_active(company_id="company-123", role="backend", user_id="user-1")

        assert plan["steps"][1]["status"] == "completed"
        assert plan["steps"][0]["status"] == "not_started"
        assert plan["steps"][2]["status"] == "not_started"
        assert plan["steps"][0]["progress"] is None

    def test_get_active_without_user_id_preserves_existing_behavior(self):
        self.generator.supabase = Mock()
        self.generator.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
            "id": "plan-123",
            "company_id": "company-123",
            "role": "backend",
            "employee_name": "Ada",
            "title": "First 7 Days — backend",
            "steps": [{"id": "step-1", "order": 1}, {"id": "step-2", "order": 2}],
            "meta": {"source": "ramp_v1"},
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }]
        self.generator.get_progress_for_plan = Mock()

        plan = self.generator.get_active(company_id="company-123", role="backend", user_id=None)

        assert "progress" not in plan
        assert "status" not in plan["steps"][0]
        assert "progress" not in plan["steps"][0]
        self.generator.get_progress_for_plan.assert_not_called()

    def _memory_supabase(self):
        rows = {
            "ramp_plans": [{
                "id": "plan-123",
                "company_id": "company-123",
                "role": "backend",
                "steps": [
                    {"id": "step-1", "order": 1},
                    {"id": "step-2", "order": 2},
                ],
                "is_active": True,
            }],
            "ramp_step_progress": [],
        }

        class FakeSupabase:
            def __init__(self, db):
                self.db = db
                self._table = None

            def table(self, name):
                self._table = name
                return self

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def upsert(self, record, on_conflict=None):
                self.db["ramp_step_progress"].append(record)
                return self

            def execute(self):
                if self._table == "ramp_plans":
                    return type("Resp", (), {"data": self.db["ramp_plans"]})()
                if self._table == "ramp_step_progress":
                    return type("Resp", (), {"data": self.db["ramp_step_progress"]})()
                return type("Resp", (), {"data": []})()

        return FakeSupabase(rows)
