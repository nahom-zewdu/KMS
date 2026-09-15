from codebase.relationships import ImplementationRelationshipExtractor


EXTRACTOR = ImplementationRelationshipExtractor()


def test_python_import_is_resolved_to_indexed_file():
    files = [
        {"path": "nlp/worker/main.py", "language": "Python", "content": "from codebase.relationships import ImplementationRelationshipExtractor\n"},
        {"path": "nlp/codebase/relationships.py", "language": "Python", "content": "class ImplementationRelationshipExtractor: ...\n"},
    ]

    relations = EXTRACTOR.extract(files)

    assert [(r.source_path, r.target_path, r.relation_type) for r in relations] == [
        ("nlp/worker/main.py", "nlp/codebase/relationships.py", "IMPORTS")
    ]


def test_python_unresolved_external_import_is_ignored():
    files = [
        {"path": "app/main.py", "language": "Python", "content": "import fastapi\n"},
    ]

    assert EXTRACTOR.extract(files) == []


def test_go_internal_import_resolves_to_package_file():
    files = [
        {"path": "go.mod", "language": "GoModule", "content": "module example.com/kms\n\ngo 1.24\n"},
        {"path": "api/github/webhook.go", "language": "Go", "content": 'import "example.com/kms/api/services"\n'},
        {"path": "api/services/github.go", "language": "Go", "content": "package services\n"},
    ]

    relations = EXTRACTOR.extract(files)

    assert [(r.source_path, r.target_path, r.relation_type) for r in relations] == [
        ("api/github/webhook.go", "api/services/github.go", "IMPORTS")
    ]


def test_go_external_import_is_ignored():
    files = [
        {"path": "go.mod", "language": "GoModule", "content": "module example.com/kms\n"},
        {"path": "main.go", "language": "Go", "content": 'import "github.com/gin-gonic/gin"\n'},
    ]

    assert EXTRACTOR.extract(files) == []


def test_relationships_are_deduplicated_and_sorted():
    files = [
        {"path": "pkg/b.py", "language": "Python", "content": "import pkg.a\nimport pkg.a\n"},
        {"path": "pkg/a.py", "language": "Python", "content": ""},
    ]

    relations = EXTRACTOR.extract(files)

    assert len(relations) == 1
    assert relations[0].source_path == "pkg/b.py"
    assert relations[0].target_path == "pkg/a.py"
