"""Tests for bounded SCIP normalization and source provenance."""

import hashlib
import json
from pathlib import Path

import pytest

from codebase.scip_indexer import ScipJobError, normalize_scip_index


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


def test_rejects_missing_source_revision(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo", encoding="utf-8")
    with pytest.raises(ValueError, match="source_revision"):
        normalize_scip_index(_index(tmp_path), repository_root=tmp_path, source_revision="")


def test_rejects_occurrence_limit(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\n", encoding="utf-8")
    with pytest.raises(ScipJobError, match="limit"):
        normalize_scip_index(
            _index(tmp_path),
            repository_root=tmp_path,
            source_revision="rev",
            max_occurrences=1,
        )



def test_accepts_empty_half_open_occurrence_range(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo\\n", encoding="utf-8")
    result = normalize_scip_index(
        _index(tmp_path, occurrences=[
            {"range": [0, 0, 0, 0], "symbol": "scip-local local x", "symbolRoles": 1},
        ]),
        repository_root=tmp_path,
        source_revision="rev",
    )
    assert len(result.occurrences) == 1
    assert result.occurrences[0].start_byte == result.occurrences[0].end_byte == 0


def test_rejects_non_utf8_document_encoding(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("foo", encoding="utf-8")
    index = _index(tmp_path, occurrences=[])
    index["metadata"]["textDocumentEncoding"] = 2
    with pytest.raises(ScipJobError, match="UTF-8"):
        normalize_scip_index(index, repository_root=tmp_path, source_revision="rev")
