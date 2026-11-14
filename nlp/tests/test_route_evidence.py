from ramp.route_evidence import GoRouteEvidenceExtractor


EXTRACTOR = GoRouteEvidenceExtractor()


def test_routes_are_resolved_to_handler_symbols_and_files():
    routes = """
func SetupRoutes() *gin.Engine {
    githubHandler := NewGitHubHandler(githubIngest, secret, storage)
    queryHandler := NewQueryHandler(slackBot, redis)
    router.POST("/github", githubHandler.HandleGitHubWebhook)
    router.POST("/query", queryHandler.HandleQuery)
}
"""
    files = [
        {"path": "api/handlers/routes.go", "content": routes},
        {"path": "api/handlers/github.go", "content": "type GitHubHandler struct {}\n"},
        {"path": "api/handlers/query.go", "content": "type QueryHandler struct {}\n"},
    ]

    evidence = EXTRACTOR.extract(files)

    assert [
        (item.method, item.path, item.handler_symbol, item.handler_file)
        for item in evidence
    ] == [
        ("POST", "/github", "GitHubHandler.HandleGitHubWebhook", "api/handlers/github.go"),
        ("POST", "/query", "QueryHandler.HandleQuery", "api/handlers/query.go"),
    ]


def test_unresolvable_handler_is_ignored_instead_of_guessed():
    files = [
        {
            "path": "api/handlers/routes.go",
            "content": 'router.POST("/unknown", missingHandler.HandleThing)\n',
        },
    ]

    assert EXTRACTOR.extract(files) == []


def test_duplicate_route_registrations_are_preserved_and_output_is_stable():
    files = [
        {
            "path": "api/handlers/routes.go",
            "content": """
handler := NewExampleHandler()
router.POST("/z", handler.Do)
router.POST("/a", handler.Do)
""",
        },
        {
            "path": "api/handlers/example.go",
            "content": "type ExampleHandler struct {}\n",
        },
    ]

    first = EXTRACTOR.extract(files)
    second = EXTRACTOR.extract(list(reversed(files)))

    assert first == second
    assert [(item.path, item.line) for item in first] == [
        ("/a", 4),
        ("/z", 3),
    ]
