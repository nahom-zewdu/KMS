from ramp.behavioral_evidence_producer import GoBehavioralEvidenceProducer


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
            assert provenance.observation == (
                "derived" if record.evidence_type == "ROUTE_HANDLER_OPERATION" else "direct"
            )
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
