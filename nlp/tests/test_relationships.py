from unittest.mock import Mock

from codebase.relationships import ImplementationRelationshipExtractor
from codebase.relationship_indexer import ImplementationRelationshipIndexer


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
        {"path": "api/go.mod", "language": "GoModule", "content": "module example.com/kms/api\n\ngo 1.24\n"},
        {"path": "api/github/webhook.go", "language": "Go", "content": 'import "example.com/kms/api/services"\n'},
        {"path": "api/services/github.go", "language": "Go", "content": "package services\n"},
    ]

    relations = EXTRACTOR.extract(files)

    assert [(r.source_path, r.target_path, r.relation_type) for r in relations] == [
        ("api/github/webhook.go", "api/services/github.go", "IMPORTS")
    ]


def test_go_external_import_is_ignored():
    files = [
        {"path": "api/go.mod", "language": "GoModule", "content": "module example.com/kms/api\n"},
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


class Query:
    def __init__(self, data):
        self.data = data
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def delete(self):
        return self

    def upsert(self, *_args, **_kwargs):
        return self

    def execute(self):
        return type("Response", (), {"data": self.data})()


def test_indexer_delete_scope_includes_all_repository_files_and_go_module():
    repository_rows = [
        {"file_path": "api/old.js", "language": "JavaScript", "repository_id": "repo-1"},
        {"file_path": "api/go.mod", "language": "Unknown", "repository_id": "repo-1"},
        {"file_path": "api/main.go", "language": "Go", "repository_id": "repo-1"},
        {"file_path": "api/services.go", "language": "Go", "repository_id": "repo-1"},
    ]
    queries = {
        "codebase_files": Query(repository_rows),
        "repositories": Query([{"id": "repo-1"}]),
        "edges": Query([]),
    }
    supabase = Mock()
    supabase.table.side_effect = lambda name: queries[name]

    class Content:
        def __init__(self, text):
            self.decoded_content = text.encode()

    repo = Mock(full_name="nahom-zewdu/KMS")
    repo.get_contents.side_effect = lambda path: {
        "api/main.go": Content('import "github.com/nahom-zewdu/kMS/api"\n'),
        "api/services.go": Content("package api\n"),
        "api/go.mod": Content("module github.com/nahom-zewdu/kMS/api\n"),
    }[path]
    github = Mock()
    github.get_repo.return_value = repo

    indexer = ImplementationRelationshipIndexer(supabase, github)
    assert indexer.index_repository("nahom-zewdu/KMS", "company-1") == 1

    old_file_id = indexer._file_entity_id("nahom-zewdu/KMS", "company-1", "api/old.js")
    assert ("source_id", old_file_id) in queries["edges"].filters
