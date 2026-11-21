"""Tests for bounded SCIP normalization and source provenance."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from codebase.scip_indexer import ScipIndexRunner, ScipJobError, normalize_scip_index


def _index(root: Path, *, relative_path: str = "src/main.py", occurrences=None):
    return {
        "metadata": {
            "version": 1,
            "projectRoot": root.as_uri(),
            "toolInfo": {"name": "test-indexer", "version": "1.2.3"},
            "textDocumentEncoding": 1,
        },
        "documents": [
            {
                "relativePath": relative_path,
                "positionEncoding": 1,
                "occurrences": occurrences if occurrences is not None else [
                    {"range": [0, 0, 0, 3], "symbol": "scip-python python pkg/main.py/main().", "symbolRoles": 1},
                    {"range": [1, 0, 1, 3], "symbol": "scip-python python pkg/main.py/main().", "symbolRoles": 8},
                ],
            }
        ],
    }


def test_normalizes_definitions_and_references_with_revision_and_hash(tmp_path):
    source = b"foo\nfoo\n"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_bytes(source)

    result = normalize_scip_index(
        _index(tmp_path),
        repository_root=tmp_path,
        source_revision="a" * 40,
    )

    assert result.indexer_name == "test-indexer"
    assert result.indexer_version == "1.2.3"
    assert len(result.occurrences) == 2
    definition, reference = result.occurrences
    assert definition.role == "definition"
    assert reference.role == "reference"
    assert definition.start_byte == 0
    assert definition.end_byte == 3
    assert definition.start_line == 1
    assert reference.start_line == 2
    assert definition.content_hash == hashlib.sha256(source).hexdigest()
    assert definition.source_revision == "a" * 40
    assert definition.occurrence_id != reference.occurrence_id


def test_normalization_is_deterministic(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\n", encoding="utf-8")
    index = _index(tmp_path, occurrences=[
        {"range": [0, 0, 0, 3], "symbol": "z", "symbolRoles": 8},
        {"range": [0, 0, 0, 3], "symbol": "a", "symbolRoles": 1},
    ])
    first = normalize_scip_index(index, repository_root=tmp_path, source_revision="rev")
    second = normalize_scip_index(index, repository_root=tmp_path, source_revision="rev")
    assert [item.to_dict() for item in first.occurrences] == [
        item.to_dict() for item in second.occurrences
    ]


@pytest.mark.parametrize("path", [
    "../outside.py",
    "/etc/passwd",
    "src\\main.py",
    "src//main.py",
    "src/./main.py",
    "C:/outside.py",
])
def test_rejects_noncanonical_or_absolute_document_paths(tmp_path, path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo", encoding="utf-8")
    with pytest.raises(ScipJobError, match="document path"):
        normalize_scip_index(
            _index(tmp_path, relative_path=path, occurrences=[]),
            repository_root=tmp_path,
            source_revision="rev",
        )


def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("foo", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "link.py").symlink_to(outside)
    try:
        with pytest.raises(ScipJobError, match="symlink"):
            normalize_scip_index(
                _index(tmp_path, relative_path="src/link.py", occurrences=[]),
                repository_root=tmp_path,
                source_revision="rev",
            )
    finally:
        outside.unlink(missing_ok=True)


def test_rejects_source_ranges_outside_file(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\n", encoding="utf-8")
    with pytest.raises(ScipJobError, match="outside"):
        normalize_scip_index(
            _index(tmp_path, occurrences=[
                {"range": [8, 0, 8, 1], "symbol": "x", "symbolRoles": 1},
            ]),
            repository_root=tmp_path,
            source_revision="rev",
        )


def test_rejects_character_offset_that_splits_utf8_codepoint(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("éx\n", encoding="utf-8")
    with pytest.raises(ScipJobError, match="splits"):
        normalize_scip_index(
            _index(tmp_path, occurrences=[
                {"range": [0, 1, 0, 2], "symbol": "x", "symbolRoles": 1},
            ]),
            repository_root=tmp_path,
            source_revision="rev",
        )


def test_rejects_unknown_position_encoding(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo", encoding="utf-8")
    index = _index(tmp_path, occurrences=[])
    index["documents"][0]["positionEncoding"] = 99
    with pytest.raises(ScipJobError, match="position encoding"):
        normalize_scip_index(index, repository_root=tmp_path, source_revision="rev")


def test_rejects_unspecified_position_encoding_without_explicit_override(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("éx\\n", encoding="utf-8")
    index = _index(tmp_path, occurrences=[
        {"range": [0, 1, 0, 2], "symbol": "x", "symbolRoles": 1},
    ])
    index["documents"][0]["positionEncoding"] = 0
    with pytest.raises(ScipJobError, match="unspecified"):
        normalize_scip_index(index, repository_root=tmp_path, source_revision="rev")


def test_uses_explicit_utf32_override_for_unspecified_position_encoding(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("éx\\n", encoding="utf-8")
    index = _index(tmp_path, occurrences=[
        {"range": [0, 1, 0, 2], "symbol": "x", "symbolRoles": 1},
    ])
    index["documents"][0]["positionEncoding"] = 0
    result = normalize_scip_index(
        index,
        repository_root=tmp_path,
        source_revision="rev",
        position_encoding_override=3,
    )
    assert result.occurrences[0].start_byte == 2
    assert result.occurrences[0].end_byte == 3


def test_rejects_missing_source_revision(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo", encoding="utf-8")
    with pytest.raises(ValueError, match="source_revision"):
        normalize_scip_index(_index(tmp_path), repository_root=tmp_path, source_revision="")


def test_rejects_occurrence_limit(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\nfoo\n", encoding="utf-8")
    with pytest.raises(ScipJobError, match="limit"):
        normalize_scip_index(
            _index(tmp_path),
            repository_root=tmp_path,
            source_revision="rev",
            max_occurrences=1,
        )



def test_accepts_empty_half_open_occurrence_range(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\n", encoding="utf-8")
    result = normalize_scip_index(
        _index(tmp_path, occurrences=[
            {"range": [0, 0, 0, 0], "symbol": "scip-local local x", "symbolRoles": 1},
        ]),
        repository_root=tmp_path,
        source_revision="rev",
    )
    assert len(result.occurrences) == 1
    assert result.occurrences[0].start_byte == result.occurrences[0].end_byte == 0


def test_normalizes_protobuf_typed_range_shape(tmp_path):
    """Accept SCIP CLI's capitalized protobuf JSON wrapper and range fields."""
    source = b"package library\n\nfunc NormalizeName(value string) string { return value }\n"
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "normalize.go").write_bytes(source)
    index = _index(
        tmp_path,
        relative_path="library/normalize.go",
        occurrences=[
            {
                "TypedRange": {
                    "SingleLineRange": {
                        "line": 2,
                        "start_character": 5,
                        "end_character": 18,
                    }
                },
                "symbol": "scip-go gomod fixture . `library`/NormalizeName().",
                "symbol_roles": 1,
            }
        ],
    )
    index["documents"][0]["position_encoding"] = 1
    result = normalize_scip_index(index, repository_root=tmp_path, source_revision="go-fixture")
    occurrence = result.occurrences[0]
    assert occurrence.role == "definition"
    assert source[occurrence.start_byte:occurrence.end_byte] == b"NormalizeName"


def test_rejects_non_utf8_document_encoding(tmp_path):

def test_runner_executes_configured_indexer_and_scip_decoder(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\nfoo\n", encoding="utf-8")
    indexer_script = tmp_path / "fake_indexer.py"
    indexer_script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path('index.scip').write_bytes(b'fake-scip-index')\n",
        encoding="utf-8",
    )
    decoder_script = tmp_path / "fake_scip.py"
    index_json = json.dumps(_index(tmp_path)).replace("\\", "\\\\")
    decoder_script.write_text(
        "import json\n"
        "print(json.dumps(json.loads(" + repr(index_json) + ")))\n",
        encoding="utf-8",
    )

    runner = ScipIndexRunner(
        indexer_argv=(sys.executable, str(indexer_script)),
        indexer_name="test-indexer",
        scip_cli_argv=(sys.executable, str(decoder_script)),
        timeout_seconds=5,
        max_index_bytes=1024,
        max_json_bytes=4096,
    )
    result = runner.run(repository_root=tmp_path, source_revision="pinned-revision")
    assert result.indexer_name == "test-indexer"
    assert [item.role for item in result.occurrences] == ["definition", "reference"]





@pytest.mark.skipif(
    os.getenv("KMS_SCIP_GO_INTEGRATION") != "1",
    reason="set KMS_SCIP_GO_INTEGRATION=1 to run the real scip-go integration",
)
def test_real_scip_go_indexes_cross_file_definition_and_reference(tmp_path):
    """Verify real Go SCIP output links a cross-package call to its definition."""
    scip_go = shutil.which("scip-go")
    scip_cli = shutil.which("scip")
    if not scip_go or not scip_cli or not shutil.which("go"):
        pytest.skip("Go, scip-go, and scip CLI must all be installed")

    (tmp_path / "go.mod").write_text(
        "module example.com/kms-scip-fixture\n\ngo 1.23\n",
        encoding="utf-8",
    )
    library = tmp_path / "library"
    consumer = tmp_path / "consumer"
    library.mkdir()
    consumer.mkdir()
    (library / "normalize.go").write_text(
        'package library\n\nimport "strings"\n\n'
        'func NormalizeName(value string) string {\n'
        '    return strings.ToLower(strings.TrimSpace(value))\n'
        '}\n',
        encoding="utf-8",
    )
    consumer_source = (
        'package consumer\n\n'
        'import "example.com/kms-scip-fixture/library"\n\n'
        'func DisplayName(value string) string {\n'
        '    return library.NormalizeName(value)\n'
        '}\n'
    )
    (consumer / "display.go").write_text(consumer_source, encoding="utf-8")

    runner = ScipIndexRunner(
        indexer_argv=(scip_go,),
        indexer_name="scip-go",
        scip_cli_argv=(scip_cli,),
        timeout_seconds=180,
        max_index_bytes=32 * 1024 * 1024,
        max_json_bytes=64 * 1024 * 1024,
    )
    result = runner.run(repository_root=tmp_path, source_revision="go-fixture-revision")

    matching = [
        item for item in result.occurrences
        if item.symbol.endswith("/NormalizeName().")
    ]
    definitions = [
        item for item in matching
        if item.role == "definition" and item.file_path == "library/normalize.go"
    ]
    references = [
        item for item in matching
        if item.role == "reference" and item.file_path == "consumer/display.go"
    ]
    assert definitions, "SCIP output did not contain NormalizeName's definition"
    assert references, "SCIP output did not link the cross-package call to NormalizeName"
    assert definitions[0].symbol == references[0].symbol

    for occurrence in (definitions[0], references[0]):
        source = (tmp_path / occurrence.file_path).read_bytes()
        assert source[occurrence.start_byte:occurrence.end_byte] == b"NormalizeName"


@pytest.mark.skipif(
    os.getenv("KMS_SCIP_PYTHON_INTEGRATION") != "1",
    reason="set KMS_SCIP_PYTHON_INTEGRATION=1 to run the real scip-python integration",
)
def test_real_scip_python_indexes_cross_file_definition_and_reference(tmp_path):
    """Verify real SCIP output links a Python call to its cross-file definition."""
    scip_python = shutil.which("scip-python")
    scip_cli = shutil.which("scip")
    if not scip_python or not scip_cli:
        pytest.skip("scip-python and scip CLI must both be installed")

    package = tmp_path / "src"
    package.mkdir()
    (package / "library.py").write_text(
        "def normalize_name(value: str) -> str:\\n"
        "    return value.strip().lower()\\n",
        encoding="utf-8",
    )
    (package / "consumer.py").write_text(
        "from library import normalize_name\\n"
        "def display_name(value: str) -> str:\\n"
        "    return normalize_name(value)\\n",
        encoding="utf-8",
    )

    runner = ScipIndexRunner(
        indexer_argv=(
            scip_python,
            "index",
            "{repository_root}",
            "--project-name=kms-scip-fixture",
            "--project-version=0.0.0",
        ),
        indexer_name="scip-python",
        scip_cli_argv=(scip_cli,),
        timeout_seconds=180,
        max_index_bytes=32 * 1024 * 1024,
        max_json_bytes=64 * 1024 * 1024,
        # SCIP's Python guidance specifies UTF-32 code-point offsets. scip-python
        # 0.6.8 omits this field, so make that compatibility assumption explicit.
        position_encoding_override=3,
    )
    result = runner.run(repository_root=tmp_path, source_revision="fixture-revision")

    matching = [
        item for item in result.occurrences
        if item.symbol.endswith("normalize_name().")
    ]
    definitions = [item for item in matching if item.role == "definition"]
    references = [
        item for item in matching
        if item.role in {"reference", "occurrence"}
        and item.file_path == "src/consumer.py"
    ]
    assert definitions, "SCIP output did not contain normalize_name's definition"
    assert references, "SCIP output did not link the cross-file call to normalize_name"
    assert definitions[0].symbol == references[0].symbol

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo", encoding="utf-8")
    index = _index(tmp_path, occurrences=[])
    index["metadata"]["textDocumentEncoding"] = 2
    with pytest.raises(ScipJobError, match="UTF-8"):
        normalize_scip_index(index, repository_root=tmp_path, source_revision="rev")


@pytest.mark.skipif(
    os.getenv("KMS_SCIP_TYPESCRIPT_INTEGRATION") != "1",
    reason="set KMS_SCIP_TYPESCRIPT_INTEGRATION=1 to run the real scip-typescript integration",
)
def test_real_scip_typescript_indexes_cross_file_definition_and_reference(tmp_path):
    """Verify real SCIP output links a TypeScript call to its cross-file definition."""
    scip_typescript = shutil.which("scip-typescript")
    scip_cli = shutil.which("scip")
    if not scip_typescript or not scip_cli or not shutil.which("node"):
        pytest.skip("Node.js, scip-typescript, and scip CLI must all be installed")

    (tmp_path / "package.json").write_text(
        '{"name":"kms-scip-fixture","version":"0.0.0","private":true}\n',
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({
            "compilerOptions": {
                "target": "ES2022",
                "module": "commonjs",
                "moduleResolution": "node",
                "strict": True,
                "skipLibCheck": True,
                "noEmit": True,
            },
            "include": ["src/**/*.ts"],
        }),
        encoding="utf-8",
    )
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    library_source = (
        "export interface User { name: string }\n"
        "export function normalizeName(value: string): string {\n"
        "    return value.trim().toLowerCase();\n"
        "}\n"
    )
    consumer_source = (
        'import { normalizeName, User } from "./library";\n'
        "export function displayName(user: User): string {\n"
        '    const marker = "😀"; return normalizeName(user.name);\n'
        "}\n"
    )
    (source_dir / "library.ts").write_text(library_source, encoding="utf-8")
    (source_dir / "consumer.ts").write_text(consumer_source, encoding="utf-8")

    runner = ScipIndexRunner(
        indexer_argv=(scip_typescript, "index", "--no-global-caches"),
        indexer_name="scip-typescript",
        scip_cli_argv=(scip_cli,),
        timeout_seconds=240,
        max_index_bytes=32 * 1024 * 1024,
        max_json_bytes=64 * 1024 * 1024,
        # scip-typescript 0.5.2 omits Document.position_encoding; SCIP specifies UTF-16 for TypeScript.
        position_encoding_override=2,
    )
    result = runner.run(repository_root=tmp_path, source_revision="typescript-fixture-revision")

    matching = [
        item for item in result.occurrences
        if "normalizeName" in item.symbol
    ]
    definitions = [
        item for item in matching
        if item.role == "definition" and item.file_path == "src/library.ts"
    ]
    references = [
        item for item in matching
        if item.role in {"reference", "occurrence"}
        and item.file_path == "src/consumer.ts"
    ]
    assert definitions, "SCIP output did not contain normalizeName's definition"
    assert references, "SCIP output did not link the cross-file call to normalizeName"
    assert definitions[0].symbol == references[0].symbol

    for occurrence in (definitions[0], references[0]):
        source = (tmp_path / occurrence.file_path).read_bytes()
        assert source[occurrence.start_byte:occurrence.end_byte] == b"normalizeName"
