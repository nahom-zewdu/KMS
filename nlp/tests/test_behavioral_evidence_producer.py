from ramp.behavioral_evidence_producer import (
    GoBehavioralEvidenceProducer,
    to_workflow_evidence,
)
from ramp.models import ImplementationSurface
from ramp.workflows import WorkflowDiscoverer


def snapshot():
    return [
        {
            "path": "api/handlers/routes.go",
            "content": """
func SetupRoutes() {
    githubHandler := NewGitHubHandler()
    router.POST("/github", githubHandler.HandleGitHubWebhook)
}
""",
        },
        {
            "path": "api/handlers/github.go",
            "content": """
type GitHubHandler struct {
    githubIngest domain.GitHubIngestService
}
func (h *GitHubHandler) HandleGitHubWebhook(c *gin.Context) {
    if err := h.githubIngest.IngestGitHubEvent(c, req); err != nil {
        return
    }
}
""",
        },
        {"path": "README.md", "content": "not source"},
    ]


def test_produces_distinct_typed_route_call_and_composed_evidence():
    records = GoBehavioralEvidenceProducer().produce(
        snapshot(), repository_id="repo-123", source_revision="a" * 40
    )

    assert {item.evidence_type for item in records} == {
        "ROUTE_HANDLES", "HANDLER_INVOKES", "ROUTE_HANDLER_OPERATION"
    }
    route = next(item for item in records if item.evidence_type == "ROUTE_HANDLES")
    call = next(item for item in records if item.evidence_type == "HANDLER_INVOKES")
    composed = next(item for item in records if item.evidence_type == "ROUTE_HANDLER_OPERATION")

    assert route.object == "GitHubHandler.HandleGitHubWebhook"
    assert call.subject == "GitHubHandler.HandleGitHubWebhook"
    assert call.object == "githubIngest.IngestGitHubEvent"
    assert composed.subject == "POST /github"
    assert composed.object == "githubIngest.IngestGitHubEvent"
    assert composed.detail.endswith("directly calls githubIngest.IngestGitHubEvent")


def test_every_record_preserves_repository_revision_and_source_locations():
    records = GoBehavioralEvidenceProducer().produce(
        snapshot(), repository_id="repo-123", source_revision="deadbeef"
    )

    assert records
    for record in records:
        assert record.ref.startswith("behavior:")
        assert record.provenance
        for provenance in record.provenance:
            assert provenance.repository_id == "repo-123"
            assert provenance.source_revision == "deadbeef"
            assert provenance.extractor_id == "kms.go.gin.behavioral"
            assert provenance.extractor_version == "1"
            assert provenance.source_file.endswith(".go")
            assert provenance.line > 0
            assert provenance.observation == "direct"
            assert provenance.limitations


def test_production_is_deterministic_and_input_order_independent():
    producer = GoBehavioralEvidenceProducer()
    first = producer.produce(snapshot(), repository_id="r", source_revision="sha")
    second = producer.produce(list(reversed(snapshot())), repository_id="r", source_revision="sha")
    assert first == second


def test_snapshot_identity_is_mandatory():
    producer = GoBehavioralEvidenceProducer()
    for kwargs in ({"repository_id": "", "source_revision": "sha"},
                   {"repository_id": "r", "source_revision": ""}):
        try:
            producer.produce(snapshot(), **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("missing snapshot identity must be rejected")


def test_duplicate_go_paths_are_rejected():
    files = snapshot() + [snapshot()[1]]
    try:
        GoBehavioralEvidenceProducer().produce(
            files, repository_id="r", source_revision="sha"
        )
    except ValueError as exc:
        assert "duplicate source path" in str(exc)
    else:
        raise AssertionError("duplicate paths must be rejected")


def test_missing_direct_call_does_not_create_composed_evidence():
    files = snapshot()
    files[1] = {
        "path": "api/handlers/github.go",
        "content": "type GitHubHandler struct {}\nfunc (h *GitHubHandler) HandleGitHubWebhook(c *gin.Context) {}",
    }
    records = GoBehavioralEvidenceProducer().produce(
        files, repository_id="r", source_revision="sha"
    )
    assert any(item.evidence_type == "ROUTE_HANDLES" for item in records)
    assert not any(item.evidence_type == "HANDLER_INVOKES" for item in records)
    assert not any(item.evidence_type == "ROUTE_HANDLER_OPERATION" for item in records)


def test_composed_records_adapt_to_qualified_workflow_evidence():
    records = GoBehavioralEvidenceProducer().produce(
        snapshot(), repository_id="repo-123", source_revision="a" * 40
    )
    evidence = to_workflow_evidence(records)

    assert len(evidence) == 1
    item = evidence[0]
    assert item.repository_id == "repo-123"
    assert item.kind == "implementation_relation"
    assert item.strength == "derived"
    assert item.metadata["relation_type"] == "ROUTE_HANDLER_OPERATION"
    assert item.metadata["source_ref"] == "api/handlers/routes.go"
    assert item.metadata["target_ref"] == "api/handlers/github.go"
    assert item.metadata["provenance"]["call_source_file"] == "api/handlers/github.go"

    surfaces = [
        ImplementationSurface(
            ref=path,
            path=path,
            repository_id="repo-123",
            module_path="api/handlers",
            language="Go",
        )
        for path in ("api/handlers/routes.go", "api/handlers/github.go")
    ]
    workflows = WorkflowDiscoverer().discover(
        surfaces, evidence, "backend-engineer"
    )
    assert workflows
    assert workflows[0].implementation_refs == [
        "api/handlers/routes.go",
        "api/handlers/github.go",
    ]
    assert item.ref in workflows[0].evidence_refs


def test_adapter_rejects_mixed_repository_or_revision_compositions():
    records = GoBehavioralEvidenceProducer().produce(
        snapshot(), repository_id="repo-123", source_revision="a" * 40
    )
    composed = next(item for item in records if item.evidence_type == "ROUTE_HANDLER_OPERATION")
    call = composed.provenance[1]
    from dataclasses import replace

    corrupted = replace(
        composed,
        provenance=(composed.provenance[0], replace(call, source_revision="b" * 40)),
    )
    assert to_workflow_evidence([corrupted]) == []
