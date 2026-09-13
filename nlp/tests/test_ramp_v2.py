from unittest.mock import Mock

from ramp.candidates import RampCandidateEngine
from ramp.generator_v2 import RampPlanner
from ramp.models import Evidence, ImplementationSurface
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


def relation(source, target, relation_type="CALLS", strength="derived"):
    """Build explicit implementation evidence for workflow discovery tests."""
    return Evidence(
        ref=f"edge:{source}:{target}",
        source="edges",
        kind="implementation_relation",
        strength=strength,
        detail=f"{source} --{relation_type}--> {target}",
        metadata={
            "source_ref": source,
            "target_ref": target,
            "relation_type": relation_type,
            "confidence": 0.8 if strength == "derived" else 1.0,
        },
    )


def test_workflow_discovery_requires_explicit_relationship_evidence():
    discoverer = WorkflowDiscoverer()
    surfaces = [surface("api/github/webhook.go"), surface("repository/redis_stream.go")]
    assert discoverer.discover(surfaces, [], "backend-engineer") == []


def test_workflow_is_derived_from_connected_implementation_evidence():
    discoverer = WorkflowDiscoverer()
    surfaces = [
        surface("api/github/webhook.go", 0.9),
        surface("api/github/service.go", 0.8),
        surface("repository/redis_stream.go", 0.7),
    ]
    evidence = [
        relation("api/github/webhook.go", "api/github/service.go"),
        relation("api/github/service.go", "repository/redis_stream.go"),
    ]
    workflows = discoverer.discover(surfaces, evidence, "backend-engineer")
    assert len(workflows) == 1
    workflow = workflows[0]
    assert workflow.confidence == "derived"
    assert all(signal["kind"] == "derived" for signal in workflow.signals)
    assert "api/github/webhook.go" in workflow.implementation_refs
    assert "github" in workflow.name


def test_weak_relationships_do_not_create_workflow_candidates():
    discoverer = WorkflowDiscoverer()
    surfaces = [surface("api/a.go"), surface("api/b.go")]
    evidence = [relation("api/a.go", "api/b.go", strength="inferred")]
    assert discoverer.discover(surfaces, evidence, "backend-engineer") == []


def test_candidate_engine_respects_stage_prerequisites():
    planner = RampPlanner(Mock())
    surfaces = [
        surface("api/github/webhook.go", 0.9),
        surface("api/github/service.go", 0.8),
        surface("repository/redis_stream.go", 0.7),
    ]
    evidence = [
        relation("api/github/webhook.go", "api/github/service.go"),
        relation("api/github/service.go", "repository/redis_stream.go"),
    ]
    workflows = planner.workflows.discover(surfaces, evidence, "backend-engineer")
    candidates = [planner.engine.from_workflow(item) for item in workflows]
    assert candidates
    assert all(planner.engine.eligible(item) for item in candidates)


def test_planner_does_not_fabricate_workflow_without_relationship_evidence():
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
    ]
    supabase = Mock()
    supabase.table.side_effect = lambda name: {
        "codebase_files": Query(files),
        "codebase_modules": Query([]),
        "entities": Query([]),
        "edges": Query([]),
        "raw_data": Query([]),
        "ramp_plans": Query([]),
        "ramp_step_progress": Query([]),
    }[name]
    planner = RampPlanner(supabase)
    planner.store.save_plan = Mock()

    plan = planner.generate("backend-engineer", "company-1", "Test Engineer")

    assert plan["meta"]["source"] == "ramp_v2"
    stages = [step["machine"]["stage"] for step in plan["steps"]]
    assert stages == ["orient", "role_surface"]
    assert all(step["machine"]["candidate_type"] != "module" for step in plan["steps"])
    assert all(step["evidence"] for step in plan["steps"])
    assert all(step["machine"]["eligible"] for step in plan["steps"])
    planner.store.save_plan.assert_called_once()
