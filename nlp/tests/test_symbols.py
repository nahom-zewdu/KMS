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
