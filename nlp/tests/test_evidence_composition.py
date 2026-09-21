from nlp.ramp.evidence_composition import GoEvidenceComposer
from nlp.ramp.handler_call_evidence import HandlerCallEvidence
from nlp.ramp.route_evidence import RouteEvidence


def route(path="/github", symbol="GitHubHandler.HandleGitHubWebhook"):
    return RouteEvidence(
        method="POST",
        path=path,
        handler_symbol=symbol,
        handler_file="api/handlers/github.go",
        route_file="api/handlers/routes.go",
        line=20,
    )


def call(field="githubIngest", method="IngestGitHubEvent", symbol="GitHubHandler.HandleGitHubWebhook"):
    return HandlerCallEvidence(
        handler_symbol=symbol,
        receiver_field=field,
        method=method,
        handler_file="api/handlers/github.go",
        line=120,
    )


def test_composes_matching_route_and_direct_operation():
    result = GoEvidenceComposer().compose([route()], [call()])

    assert len(result) == 1
    assert result[0].path == "/github"
    assert result[0].handler_symbol == "GitHubHandler.HandleGitHubWebhook"
    assert result[0].next_inspection_target == "githubIngest.IngestGitHubEvent"


def test_multiple_routes_and_calls_are_preserved_deterministically():
    routes = [route("/github/"), route("/github")]
    calls = [
        call("storage", "Save"),
        call("githubIngest", "IngestGitHubEvent"),
    ]

    result = GoEvidenceComposer().compose(routes, calls)

    assert [(item.path, item.operation) for item in result] == [
        ("/github", "IngestGitHubEvent"),
        ("/github", "Save"),
        ("/github/", "IngestGitHubEvent"),
        ("/github/", "Save"),
    ]


def test_unmatched_route_produces_no_invented_composition():
    result = GoEvidenceComposer().compose(
        [route(symbol="MissingHandler.Handle")],
        [call()],
    )

    assert result == []


def test_same_symbol_in_different_file_does_not_cross_join():
    other_call = HandlerCallEvidence(
        handler_symbol="GitHubHandler.HandleGitHubWebhook",
        receiver_field="other",
        method="WrongFileOperation",
        handler_file="api/other.go",
        line=10,
    )

    result = GoEvidenceComposer().compose([route()], [call(), other_call])

    assert [item.operation for item in result] == ["IngestGitHubEvent"]


def test_composition_preserves_direct_call_evidence_without_claiming_implementation():
    result = GoEvidenceComposer().compose([route()], [call()])

    assert result[0].receiver_field == "githubIngest"
    assert result[0].operation == "IngestGitHubEvent"
    assert result[0].call_file == "api/handlers/github.go"
