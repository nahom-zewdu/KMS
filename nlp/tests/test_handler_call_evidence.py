from ramp.handler_call_evidence import GoHandlerCallEvidenceExtractor


EXTRACTOR = GoHandlerCallEvidenceExtractor()


def test_direct_injected_dependency_calls_are_detected():
    source = """
type GitHubHandler struct {
    githubIngest domain.GitHubIngestService
    secret string
}

func (h *GitHubHandler) HandleGitHubWebhook(c *gin.Context) {
    if !h.verify(c) {
        return
    }
    if err := h.githubIngest.IngestGitHubEvent(c, req); err != nil {
        return
    }
}

func (h *GitHubHandler) verify(c *gin.Context) bool {
    return true
}
"""
    evidence = EXTRACTOR.extract(
        source,
        path="api/handlers/github.go",
        handler_symbol="GitHubHandler.HandleGitHubWebhook",
    )

    assert [(item.receiver_field, item.method) for item in evidence] == [
        ("githubIngest", "IngestGitHubEvent"),
    ]


def test_unrelated_package_calls_are_ignored():
    source = """
type QueryHandler struct {
    redis domain.RedisStream
}

func (h *QueryHandler) HandleQuery(c *gin.Context) {
    json.Unmarshal(body, &req)
    h.redis.Publish(c, job)
    time.Now()
}
"""
    evidence = EXTRACTOR.extract(
        source,
        path="api/handlers/query.go",
        handler_symbol="QueryHandler.HandleQuery",
    )

    assert [(item.receiver_field, item.method) for item in evidence] == [
        ("redis", "Publish"),
    ]


def test_missing_handler_field_abstains():
    source = """
type ExampleHandler struct {
    storage domain.StoragePort
}

func (h *ExampleHandler) Handle(c *gin.Context) {
    h.missing.Do(c)
}
"""
    assert EXTRACTOR.extract(
        source,
        path="api/handlers/example.go",
        handler_symbol="ExampleHandler.Handle",
    ) == []


def test_multiple_dependency_calls_preserve_source_order():
    source = """
type QueryHandler struct {
    redis domain.RedisStream
}

func (h *QueryHandler) HandleQuery(c *gin.Context) {
    h.redis.Subscribe(c, "result")
    h.redis.Publish(c, "job")
}
"""
    evidence = EXTRACTOR.extract(
        source,
        path="api/handlers/query.go",
        handler_symbol="QueryHandler.HandleQuery",
    )

    assert [(item.receiver_field, item.method, item.line) for item in evidence] == [
        ("redis", "Subscribe", 7),
        ("redis", "Publish", 8),
    ]


def test_interface_implementation_is_not_resolved():
    source = """
type ExampleHandler struct {
    service domain.SomeService
}

func (h *ExampleHandler) Handle(c *gin.Context) {
    h.service.Do(c)
}
"""
    evidence = EXTRACTOR.extract(
        source,
        path="api/handlers/example.go",
        handler_symbol="ExampleHandler.Handle",
    )

    assert [(item.receiver_field, item.method) for item in evidence] == [
        ("service", "Do"),
    ]
