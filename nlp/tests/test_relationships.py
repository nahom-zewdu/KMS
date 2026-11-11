from unittest.mock import Mock

from github import GithubException

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
    supabase.rpc.return_value.execute.return_value = Mock(data=1)

    class Content:
        def __init__(self, text):
            self.decoded_content = text.encode()

    repo = Mock(full_name="nahom-zewdu/KMS")
    repo.get_contents.side_effect = lambda path, ref=None: {
        "api/main.go": Content('import "github.com/nahom-zewdu/kMS/api"\n'),
        "api/services.go": Content("package api\n"),
        "api/go.mod": Content("module github.com/nahom-zewdu/kMS/api\n"),
    }[path]
    github = Mock()
    github.get_repo.return_value = repo

    indexer = ImplementationRelationshipIndexer(supabase, github)
    assert indexer.index_repository(
        "nahom-zewdu/KMS", "company-1", source_revision="a" * 40
    ) == 1

    old_file_id = indexer._file_entity_id("nahom-zewdu/KMS", "company-1", "api/old.js")
    rpc_name, rpc_args = supabase.rpc.call_args.args
    assert rpc_name == "replace_implementation_edges"
    assert old_file_id in rpc_args["p_source_ids"]
    assert rpc_args["p_edges"][0]["type"] == "IMPORTS"
    assert not queries["edges"].filters



def test_deleted_go_file_in_stale_inventory_is_skipped_for_current_snapshot():
    class Content:
        decoded_content = b"package current"

    repo = Mock()
    repo.get_contents.side_effect = lambda path, ref=None: (
        (_ for _ in ()).throw(GithubException(404, {"message": "Not Found"}, {}))
        if path == "api/deleted.go"
        else Content()
    )
    indexer = ImplementationRelationshipIndexer(Mock(), Mock())

    inventory = indexer._load_source_inventory(
        repo,
        [
            {"file_path": "api/deleted.go", "language": "Go"},
            {"file_path": "api/current.go", "language": "Go"},
        ],
        ref="a" * 40,
    )

    assert inventory == [
        {"path": "api/current.go", "language": "Go", "content": "package current"}
    ]


def test_unavailable_go_file_fails_closed_when_not_deleted():
    repo = Mock()
    repo.get_contents.side_effect = GithubException(
        403, {"message": "Forbidden"}, {}
    )
    indexer = ImplementationRelationshipIndexer(Mock(), Mock())

    try:
        indexer._load_source_inventory(
            repo,
            [{"file_path": "api/private.go", "language": "Go"}],
            ref="a" * 40,
        )
    except RuntimeError as exc:
        assert "Cannot build complete Go behavioral snapshot" in str(exc)
    else:
        raise AssertionError("unavailable Go source must fail closed")
