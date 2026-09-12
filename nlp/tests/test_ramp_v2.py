from unittest.mock import Mock

from ramp.candidates import RampCandidateEngine
from ramp.generator_v2 import RampPlanner
from ramp.models import ImplementationSurface
from ramp.workflows import WorkflowDiscoverer


class Query:
    """Minimal Supabase query double for Ramp planner tests."""

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


def surface(path, importance=0.5, author="alice"):
    return ImplementationSurface(
        ref=path,
        path=path,
        repository_id="repo-1",
        module_path="/".join(path.split("/")[:-1]),
        language="Go",
        importance=importance,
        last_author=author,
    )


def test_workflow_discovery_requires_multiple_surfaces():
    discoverer = WorkflowDiscoverer()
    evidence = []
    assert discoverer.discover([surface("api/github.go")], evidence, "backend-engineer") == []


def test_workflow_is_explicitly_inferred_from_indexed_structure():
    discoverer = WorkflowDiscoverer()
    surfaces = [
        surface("api/github/webhook.go", 0.9),
        surface("api/github/service.go", 0.8),
        surface("repository/redis_stream.go", 0.7),
    ]
    workflows = discoverer.discover(surfaces, [], "backend-engineer")
    github = next(item for item in workflows if item.name == "github ingestion")
    assert github.confidence == "derived"
    assert all(signal["kind"] == "inferred" for signal in github.signals)
    assert "api/github/webhook.go" in github.implementation_refs


def test_candidate_engine_respects_stage_prerequisites():
    planner = RampPlanner(Mock())
    surfaces = [
        surface("api/github/webhook.go", 0.9),
        surface("api/github/service.go", 0.8),
        surface("repository/redis_stream.go", 0.7),
        surface("api/query.go", 0.6),
    ]
    evidence = [planner.evidence.evidence_for_surface(item) for item in surfaces]
    workflows = planner.workflows.discover(surfaces, evidence, "backend-engineer")
    candidates = [planner.engine.from_workflow(item) for item in workflows]
    assert candidates
    assert all(planner.engine.eligible(item) for item in candidates)


def test_planner_generates_ordered_outcomes_from_company_index():
    files = [
        {
            "id": "f1", "repository_id": "r1", "file_path": "api/github/webhook.go",
            "module_path": "api/github", "language": "Go", "last_author": "alice",
            "last_commit_sha": "a1", "importance_score": 0.9, "metadata": {},
        },
        {
            "id": "f2", "repository_id": "r1", "file_path": "api/github/service.go",
            "module_path": "api/github", "language": "Go", "last_author": "bob",
            "last_commit_sha": "a2", "importance_score": 0.8, "metadata": {},
        },
        {
            "id": "f3", "repository_id": "r1", "file_path": "repository/redis_stream.go",
            "module_path": "repository", "language": "Go", "last_author": "bob",
            "last_commit_sha": "a3", "importance_score": 0.7, "metadata": {},
        },
    ]
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "codebase_files": Query(files),
        "codebase_modules": Query([]),
        "edges": Query([]),
        "raw_data": Query([]),
        "ramp_plans": Query([]),
        "ramp_step_progress": Query([]),
    }[name]
    planner = RampPlanner(supabase)
    planner.store.save_plan = Mock()

    plan = planner.generate("backend-engineer", "company-1", "Test Engineer")

    assert plan["meta"]["source"] == "ramp_v2"
    assert [step["machine"]["stage"] for step in plan["steps"]] == [
        "orient", "role_surface", "workflow"
    ]
    assert all(step["machine"]["candidate_type"] != "module" for step in plan["steps"])
    assert all(step["evidence"] for step in plan["steps"])
    assert all(step["machine"]["eligible"] for step in plan["steps"])
    planner.store.save_plan.assert_called_once()
