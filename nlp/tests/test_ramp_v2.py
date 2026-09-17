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
    assert workflow.name.endswith("implementation flow")
    assert workflow.implementation_refs == [
            "api/github/webhook.go",
            "api/github/service.go",
            "repository/redis_stream.go",
        ]

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


def test_large_component_is_decomposed_into_bounded_paths():
    discoverer = WorkflowDiscoverer()
    paths = [
        ["api/entry.go", "api/validate.go", "api/service.go", "api/store.go", "api/queue.go", "api/worker.go", "api/result.go", "api/audit.go", "api/extra.go"],
        ["api/entry.go", "api/validate.go", "api/service.go", "api/store.go", "api/queue.go", "api/notify.go"],
    ]
    surfaces = [surface(path, importance=1.0 - index * 0.02) for index, path in enumerate(sorted({item for path in paths for item in path}))]
    evidence = [relation(source, target) for path in paths for source, target in zip(path, path[1:])]

    workflows = discoverer.discover(surfaces, evidence, "backend-engineer")

    assert len(workflows) == 2
    assert all(2 <= len(item.implementation_refs) <= discoverer._MAX_PATH_FILES for item in workflows)
    assert all("api/extra.go" not in item.implementation_refs for item in workflows)
    assert any("api/audit.go" in item.implementation_refs for item in workflows)
    assert any("api/notify.go" in item.implementation_refs for item in workflows)


def test_workflow_decomposition_is_deterministic_and_evidence_bounded():
    discoverer = WorkflowDiscoverer()
    surfaces = [surface("api/a.go"), surface("api/b.go"), surface("api/c.go")]
    evidence = [relation("api/a.go", "api/b.go"), relation("api/b.go", "api/c.go")]

    first = discoverer.discover(surfaces, evidence, "backend-engineer")
    second = discoverer.discover(list(reversed(surfaces)), list(reversed(evidence)), "backend-engineer")

    assert first == second
    known_paths = {item.path for item in surfaces}
    known_evidence = {item.ref for item in evidence}
    for workflow in first:
        assert set(workflow.implementation_refs) <= known_paths
        assert set(workflow.evidence_refs) <= known_paths | known_evidence
        assert all(signal["from"] in known_paths and signal["to"] in known_paths for signal in workflow.signals)


def test_cycles_hubs_and_isolated_files_remain_bounded():
    discoverer = WorkflowDiscoverer()
    surfaces = [
        surface("pkg/cycle_a.go"),
        surface("pkg/cycle_b.go"),
        surface("pkg/hub.go"),
        surface("pkg/leaf_a.go"),
        surface("pkg/leaf_b.go"),
        surface("pkg/isolated.go"),
    ]
    evidence = [
        relation("pkg/cycle_a.go", "pkg/cycle_b.go"),
        relation("pkg/cycle_b.go", "pkg/cycle_a.go"),
        relation("pkg/hub.go", "pkg/leaf_a.go"),
        relation("pkg/hub.go", "pkg/leaf_b.go"),
    ]

    workflows = discoverer.discover(surfaces, evidence, "backend-engineer")

    assert workflows
    assert all(len(item.implementation_refs) <= discoverer._MAX_PATH_FILES for item in workflows)
    assert all("pkg/isolated.go" not in item.implementation_refs for item in workflows)
    assert any(set(item.implementation_refs) == {"pkg/cycle_a.go", "pkg/cycle_b.go"} for item in workflows)
    assert len(workflows) <= discoverer._MAX_CANDIDATES_PER_COMPONENT * 2


def test_decomposition_abstains_when_no_meaningful_path_exists():
    discoverer = WorkflowDiscoverer()
    surfaces = [surface("pkg/a.go"), surface("pkg/b.go")]
    evidence = [relation("pkg/a.go", "pkg/b.go", strength="inferred")]

    assert discoverer.discover(surfaces, evidence, "backend-engineer") == []
