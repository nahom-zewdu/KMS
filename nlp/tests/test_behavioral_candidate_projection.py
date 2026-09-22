from nlp.ramp.behavioral_candidate_projection import GoBehavioralCandidateProjector
from nlp.ramp.evidence_composition import ComposedRouteEvidence


def item(**overrides):
    values = dict(
        method="POST",
        path="/github",
        handler_symbol="GitHubHandler.HandleGitHubWebhook",
        handler_file="api/handlers/github.go",
        route_file="api/handlers/routes.go",
        route_line=42,
        receiver_field="githubIngest",
        operation="IngestGitHubEvent",
        call_file="api/handlers/github.go",
        call_line=91,
    )
    values.update(overrides)
    return ComposedRouteEvidence(**values)


def test_projects_github_boundary():
    result = GoBehavioralCandidateProjector().project([item()])
    assert len(result) == 1
    candidate = result[0]
    assert candidate.evidence_type == "ROUTE_HANDLER_DIRECT_OPERATION"
    assert candidate.next_inspection_target == "githubIngest.IngestGitHubEvent"
    assert candidate.behavior_statement == (
        "POST /github is registered to GitHubHandler.HandleGitHubWebhook, "
        "which directly calls githubIngest.IngestGitHubEvent."
    )


def test_preserves_slack_branches_as_separate_units():
    result = GoBehavioralCandidateProjector().project([
        item(
            path="/slack/events",
            handler_symbol="SlackHandler.HandleSlackWebhook",
            handler_file="api/handlers/slack.go",
            receiver_field="slackBot",
            operation="HandleEvent",
            call_line=80,
        ),
        item(
            path="/slack/events",
            handler_symbol="SlackHandler.HandleSlackWebhook",
            handler_file="api/handlers/slack.go",
            receiver_field="slackIngest",
            operation="IngestSlackEvent",
            call_line=95,
        ),
    ])
    assert [x.operation for x in result] == ["HandleEvent", "IngestSlackEvent"]
    assert len({x.candidate_id for x in result}) == 2


def test_query_transport_boundary_is_preserved():
    result = GoBehavioralCandidateProjector().project([
        item(
            path="/query",
            handler_symbol="QueryHandler.HandleQuery",
            handler_file="api/handlers/query.go",
            receiver_field="redis",
            operation="Subscribe",
            call_line=70,
        ),
        item(
            path="/query",
            handler_symbol="QueryHandler.HandleQuery",
            handler_file="api/handlers/query.go",
            receiver_field="redis",
            operation="Publish",
            call_line=76,
        ),
    ])
    assert [x.operation for x in result] == ["Subscribe", "Publish"]


def test_deterministic_ordering():
    evidence = [item(operation="Zed", call_line=100), item(operation="Alpha", call_line=90)]
    first = GoBehavioralCandidateProjector().project(evidence)
    second = GoBehavioralCandidateProjector().project(list(reversed(evidence)))
    assert first == second
    assert [x.operation for x in first] == ["Alpha", "Zed"]


def test_projection_does_not_invent_unmatched_evidence():
    assert GoBehavioralCandidateProjector().project([]) == []


def test_same_handler_symbol_can_remain_distinct_by_source_boundary():
    result = GoBehavioralCandidateProjector().project([
        item(handler_file="a.go", operation="First"),
        item(handler_file="b.go", operation="Second"),
    ])
    assert len(result) == 2
    assert result[0].handler_file == "a.go"
    assert result[1].handler_file == "b.go"
