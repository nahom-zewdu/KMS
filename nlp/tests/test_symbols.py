from pathlib import Path

from codebase.symbols import CodeSymbolExtractor


EXTRACTOR = CodeSymbolExtractor()
REVISION = "a" * 40


def test_python_symbols_include_classes_functions_and_decorated_line_spans():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1",
        file_path="nlp/example.py",
        source="""@dataclass
class Worker:
    def run(self):
        return True

def build():
    return Worker()
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert result.language == "Python"
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("Worker", "class"),
        ("Worker.run", "method"),
        ("build", "function"),
    ]
    assert result.symbols[0].start_line == 1


def test_go_symbols_distinguish_types_functions_and_receiver_methods():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1",
        file_path="api/worker.go",
        source="""package api

type Worker struct {}
type Runner interface { Run() }

func Build() *Worker { return nil }
func (w *Worker) Run() {}
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("Worker", "struct"),
        ("Runner", "interface"),
        ("Build", "function"),
        ("Worker.Run", "method"),
    ]


def test_typescript_symbols_include_interfaces_classes_methods_and_functions():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1",
        file_path="src/worker.ts",
        source="""interface Store { save(): void }
class Worker {
  run() {}
}
function build(): Worker { return new Worker(); }
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("Store", "interface"),
        ("Worker", "class"),
        ("Worker.run", "method"),
        ("build", "function"),
    ]


def test_javascript_symbols_are_supported():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1",
        file_path="src/worker.js",
        source="class Worker { run() {} }\nfunction build() {}\n",
        source_revision=REVISION,
    )

    assert result is not None
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("Worker", "class"),
        ("Worker.run", "method"),
        ("build", "function"),
    ]


def test_symbol_identity_is_stable_across_revisions_but_provenance_changes():
    source = "def run():\n    pass\n"
    first = EXTRACTOR.extract_file(
        repository_id="repo-1", file_path="src/worker.py",
        source=source, source_revision="a" * 40,
    )
    second = EXTRACTOR.extract_file(
        repository_id="repo-1", file_path="src/worker.py",
        source=source, source_revision="b" * 40,
    )

    assert first is not None and second is not None
    assert first.symbols[0].symbol_id == second.symbols[0].symbol_id
    assert first.symbols[0].source_revision != second.symbols[0].source_revision


def test_unsupported_language_and_missing_revision_are_not_indexed():
    assert EXTRACTOR.extract_file(
        repository_id="repo-1", file_path="README.md",
        source="# docs", source_revision=REVISION,
    ) is None
    assert EXTRACTOR.extract_file(
        repository_id="repo-1", file_path="main.py",
        source="pass", source_revision="",
    ) is None


def test_syntax_errors_are_reported_without_claiming_clean_parse():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1", file_path="broken.py",
        source="def broken(:\n    pass\n", source_revision=REVISION,
    )

    assert result is not None
    assert result.has_syntax_errors


def test_kms_go_handler_source_shape_extracts_struct_constructor_and_receiver_method():
    # Representative declarations copied from api/handlers/github.go.
    result = EXTRACTOR.extract_file(
        repository_id="kms",
        file_path="api/handlers/github.go",
        source="""package handlers

type GitHubHandler struct {
    githubIngest domain.GitHubIngestService
    secret string
    storage domain.StoragePort
}

func NewGitHubHandler(githubIngest domain.GitHubIngestService, secret string, storage domain.StoragePort) *GitHubHandler {
    return &GitHubHandler{githubIngest: githubIngest, secret: secret, storage: storage}
}

func (h *GitHubHandler) HandleGitHubWebhook(c *gin.Context) {
    _ = h.storage
}
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("GitHubHandler", "struct"),
        ("NewGitHubHandler", "function"),
        ("GitHubHandler.HandleGitHubWebhook", "method"),
    ]


def test_kms_python_baseline_source_shape_extracts_class_methods_and_nested_helpers():
    # Representative declarations copied from nlp/codebase/baseline.py.
    result = EXTRACTOR.extract_file(
        repository_id="kms",
        file_path="nlp/codebase/baseline.py",
        source="""class CodebaseBaselineSync:
    def __init__(self, supabase):
        self.supabase = supabase

    def sync_repository(self, repo_full_name, company_id):
        def ensure_lease():
            return True

        def renew_lease():
            return ensure_lease()

        return renew_lease()
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("CodebaseBaselineSync", "class"),
        ("CodebaseBaselineSync.__init__", "method"),
        ("CodebaseBaselineSync.sync_repository", "method"),
        ("ensure_lease", "function"),
        ("renew_lease", "function"),
    ]


def test_kms_frontend_tsx_source_shape_extracts_interface_and_default_component():
    # Representative declarations copied from kms-frontend/app/dashboard/settings/UserList.tsx.
    result = EXTRACTOR.extract_file(
        repository_id="kms-frontend",
        file_path="app/dashboard/settings/UserList.tsx",
        source="""'use client';
interface User {
    id: string;
    email: string;
    name: string;
    role: string;
}

export default function UserList() {
    return <div>Team members</div>;
}
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert result.language == "TSX"
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("User", "interface"),
        ("UserList", "function"),
    ]




def test_repository_go_source_has_representative_declaration_coverage():
    """Exercise the extractor against the checked-in GitHub webhook implementation."""
    repository_root = Path(__file__).resolve().parents[2]
    source_path = repository_root / "api" / "handlers" / "github.go"
    source = source_path.read_text(encoding="utf-8")

    result = EXTRACTOR.extract_file(
        repository_id="kms",
        file_path="api/handlers/github.go",
        source=source,
        source_revision=REVISION,
    )

    assert result is not None
    assert not result.has_syntax_errors
    qualified_names = {symbol.qualified_name for symbol in result.symbols}
    expected = {
        "GitHubHandler",
        "NewGitHubHandler",
        "extractRichContent",
        "extractIssueSnapshot",
        "truncateText",
        "extractIssueLabels",
        "getString",
        "interfaceSlice",
        "summarizeFiles",
        "inferContextFromFiles",
        "GitHubHandler.HandleGitHubWebhook",
        "extractHeadCommit",
        "GitHubHandler.verifyGitHubSignature",
    }
    assert expected <= qualified_names
    assert len(result.symbols) >= len(expected)


def test_repository_python_source_has_representative_declaration_coverage():
    """Exercise nested and class-scoped declarations in the checked-in baseline syncer."""
    repository_root = Path(__file__).resolve().parents[2]
    source_path = repository_root / "nlp" / "codebase" / "baseline.py"
    source = source_path.read_text(encoding="utf-8")

    result = EXTRACTOR.extract_file(
        repository_id="kms",
        file_path="nlp/codebase/baseline.py",
        source=source,
        source_revision=REVISION,
    )

    assert result is not None
    assert not result.has_syntax_errors
    qualified_names = {symbol.qualified_name for symbol in result.symbols}
    expected = {
        "CodebaseBaselineSync",
        "CodebaseBaselineSync.__init__",
        "CodebaseBaselineSync.sync_repository",
        "ensure_lease",
        "renew_lease",
        "CodebaseBaselineSync._backfill_issue_events",
        "CodebaseBaselineSync._index_file",
        "CodebaseBaselineSync._create_module",
    }
    assert expected <= qualified_names
    assert len(result.symbols) >= len(expected)



def test_typescript_indexes_arrow_functions_and_interface_method_signatures():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1",
        file_path="src/service.ts",
        source="""interface Store {
  save(): void;
}
export const build = () => new Worker();
class Worker {
  run = async () => true;
}
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert not result.has_syntax_errors
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("Store", "interface"),
        ("Store.save", "method"),
        ("build", "function"),
        ("Worker", "class"),
        ("Worker.run", "method"),
    ]


def test_python_async_functions_are_extracted():
    result = EXTRACTOR.extract_file(
        repository_id="repo-1",
        file_path="src/worker.py",
        source="""async def run_job():
    return True
""",
        source_revision=REVISION,
    )

    assert result is not None
    assert not result.has_syntax_errors
    assert [(item.qualified_name, item.kind) for item in result.symbols] == [
        ("run_job", "function"),
    ]
