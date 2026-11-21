"""Bounded SCIP job execution and revision-pinned occurrence normalization.

This module consumes SCIP through the upstream `scip print --json` CLI.
It deliberately does not infer semantic edges from source names or syntax.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import tempfile
import shutil
import time
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import unquote, urlparse


class ScipJobError(RuntimeError):
    """A SCIP job failed with an explicit machine-readable status."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ScipOccurrence:
    """One semantic definition or reference tied to an immutable source revision."""

    occurrence_id: str
    file_path: str
    symbol: str
    role: str
    symbol_roles: int
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    content_hash: str
    source_revision: str
    indexer_name: str
    indexer_version: str
    protocol_version: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable normalized occurrence."""
        return {
            "occurrence_id": self.occurrence_id,
            "file_path": self.file_path,
            "symbol": self.symbol,
            "role": self.role,
            "symbol_roles": self.symbol_roles,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "content_hash": self.content_hash,
            "source_revision": self.source_revision,
            "indexer_name": self.indexer_name,
            "indexer_version": self.indexer_version,
            "protocol_version": self.protocol_version,
        }


@dataclass(frozen=True)
class ScipIndex:
    """Validated metadata and semantic occurrences from one SCIP index."""

    indexer_name: str
    indexer_version: str
    protocol_version: int
    occurrences: tuple[ScipOccurrence, ...]


def normalize_scip_index(
    index: dict[str, Any],
    *,
    repository_root: str | Path,
    source_revision: str,
    max_occurrences: int = 1_000_000,
    position_encoding_override: int | None = None,
) -> ScipIndex:
    """Validate SCIP paths and source ranges, then normalize definitions/references.

    The SCIP index must describe exactly the supplied checkout. Unknown position
    encodings, non-canonical paths, symlinks, missing files, malformed ranges,
    and out-of-bounds spans fail closed.
    """
    if not source_revision or not source_revision.strip():
        raise ValueError("source_revision is required")
    if max_occurrences < 1:
        raise ValueError("max_occurrences must be positive")
    if position_encoding_override not in {None, 1, 2, 3}:
        raise ValueError("position_encoding_override must be one of 1, 2, or 3")

    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise ScipJobError("invalid_repository_root", "repository root is not a directory")

    metadata = index.get("metadata")
    if not isinstance(metadata, dict):
        raise ScipJobError("malformed_index", "SCIP metadata is missing")
    project_root = _get(metadata, "projectRoot", "project_root")
    if not isinstance(project_root, str) or _resolve_project_root(project_root) != root:
        raise ScipJobError("revision_root_mismatch", "SCIP project root does not match the pinned checkout")

    tool_info = _get(metadata, "toolInfo", "tool_info")
    if not isinstance(tool_info, dict):
        raise ScipJobError("malformed_index", "SCIP indexer metadata is missing")
    indexer_name = tool_info.get("name")
    indexer_version = tool_info.get("version")
    if not isinstance(indexer_name, str) or not indexer_name.strip():
        raise ScipJobError("malformed_index", "SCIP indexer name is missing")
    if not isinstance(indexer_version, str) or not indexer_version.strip():
        raise ScipJobError("malformed_index", "SCIP indexer version is missing")

    protocol_version = _get(metadata, "version", default=0)
    if not isinstance(protocol_version, int) or protocol_version < 0:
        raise ScipJobError("malformed_index", "invalid SCIP protocol version")

    text_encoding = _get(metadata, "textDocumentEncoding", "text_document_encoding")
    if text_encoding != 1:
        raise ScipJobError("unsupported_text_encoding", "only UTF-8 source documents are supported")

    documents = index.get("documents")
    if not isinstance(documents, list):
        raise ScipJobError("malformed_index", "SCIP documents must be an array")

    normalized: list[ScipOccurrence] = []
    for document in documents:
        if not isinstance(document, dict):
            raise ScipJobError("malformed_index", "SCIP document must be an object")
        relative_path = _get(document, "relativePath", "relative_path")
        source_path = _validated_source_path(root, relative_path)
        try:
            source = source_path.read_bytes()
        except OSError as exc:
            raise ScipJobError("invalid_document", f"unable to read SCIP document: {relative_path}") from exc

        position_encoding = _get(document, "positionEncoding", "position_encoding", default=0)
        if position_encoding == 0:
            # SCIP defines zero as unspecified; only an explicit, indexer-specific
            # override may resolve it. Never guess from the file extension.
            position_encoding = position_encoding_override
        if position_encoding not in {1, 2, 3}:
            raise ScipJobError(
                "unsupported_position_encoding",
                f"SCIP position encoding is unspecified or unsupported for {relative_path}",
            )

        content_hash = hashlib.sha256(source).hexdigest()
        occurrences = document.get("occurrences", [])
        if not isinstance(occurrences, list):
            raise ScipJobError("malformed_index", "SCIP occurrences must be an array")

        for occurrence in occurrences:
            if len(normalized) >= max_occurrences:
                raise ScipJobError("occurrence_limit_exceeded", "SCIP occurrence limit exceeded")
            if not isinstance(occurrence, dict):
                raise ScipJobError("malformed_index", "SCIP occurrence must be an object")
            symbol = occurrence.get("symbol")
            if not symbol:
                continue
            if not isinstance(symbol, str):
                raise ScipJobError("malformed_index", "SCIP symbol must be a string")
            roles = _get(occurrence, "symbolRoles", "symbol_roles", default=0)
            if not isinstance(roles, int) or roles < 0:
                raise ScipJobError("malformed_index", "SCIP symbol roles must be a non-negative integer")
            role = "definition" if roles & 1 else ("reference" if roles else "occurrence")
            start_line, start_character, end_line, end_character = _occurrence_range(occurrence)
            start_byte = _position_to_byte(source, start_line, start_character, position_encoding)
            end_byte = _position_to_byte(source, end_line, end_character, position_encoding)
            if end_byte < start_byte:
                raise ScipJobError("invalid_range", f"reversed SCIP range in {relative_path}")

            identity = "\0".join((
                source_revision, relative_path, symbol, str(roles),
                str(start_byte), str(end_byte),
            ))
            occurrence_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            normalized.append(ScipOccurrence(
                occurrence_id=occurrence_id,
                file_path=relative_path,
                symbol=symbol,
                role=role,
                symbol_roles=roles,
                start_line=start_line + 1,
                end_line=end_line + 1,
                start_byte=start_byte,
                end_byte=end_byte,
                content_hash=content_hash,
                source_revision=source_revision,
                indexer_name=indexer_name,
                indexer_version=indexer_version,
                protocol_version=protocol_version,
            ))

    normalized.sort(key=lambda item: (item.file_path, item.start_byte, item.end_byte, item.symbol))
    return ScipIndex(
        indexer_name=indexer_name,
        indexer_version=indexer_version,
        protocol_version=protocol_version,
        occurrences=tuple(normalized),
    )


class ScipIndexRunner:
    """Run a configured language indexer and decode its output without a shell."""

    def __init__(
        self,
        *,
        indexer_argv: Sequence[str],
        indexer_name: str,
        scip_cli_argv: Sequence[str] = ("scip",),
        timeout_seconds: int = 600,
        max_index_bytes: int = 100 * 1024 * 1024,
        max_json_bytes: int = 100 * 1024 * 1024,
        position_encoding_override: int | None = None,
    ) -> None:
        if not indexer_argv or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in indexer_argv):
            raise ValueError("indexer_argv must contain non-empty argument strings")
        if not scip_cli_argv or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in scip_cli_argv):
            raise ValueError("scip_cli_argv must contain non-empty argument strings")
        if timeout_seconds < 1 or max_index_bytes < 1 or max_json_bytes < 1:
            raise ValueError("SCIP job limits must be positive")
        if position_encoding_override not in {None, 1, 2, 3}:
            raise ValueError("position_encoding_override must be one of 1, 2, or 3")
        self.position_encoding_override = position_encoding_override
        self.indexer_argv = tuple(indexer_argv)
        self.indexer_name = indexer_name
        self.scip_cli_argv = tuple(scip_cli_argv)
        self.timeout_seconds = timeout_seconds
        self.max_index_bytes = max_index_bytes
        self.max_json_bytes = max_json_bytes

    def run(
        self,
        *,
        repository_root: str | Path,
        source_revision: str,
        index_path: str = "index.scip",
    ) -> ScipIndex:
        """Execute an indexer in a temporary working directory and normalize its output.

        The indexer receives the immutable checkout through {repository_root};
        its default index.scip output is collected from the temporary working
        directory. Indexers supporting an output argument may instead consume
        {index_path}. The caller must provide an isolated checkout: this class
        does not sandbox arbitrary build hooks or impose OS-level resource limits.
        """
        root = Path(repository_root).resolve(strict=True)
        if not root.is_dir():
            raise ScipJobError("invalid_repository_root", "repository root is not a directory")
        relative_index = PurePosixPath(index_path)
        if relative_index.is_absolute() or PureWindowsPath(index_path).is_absolute() or PureWindowsPath(index_path).drive or any(part in {"", ".", ".."} for part in index_path.split("/")):
            raise ValueError("index_path must be a canonical relative path")

        # SCIP indexers resolve projectRoot from their working directory.
        # Run inside the pinned checkout so the index metadata and source files
        # share one root. The conventional index.scip artifact is moved into the
        # temporary job directory immediately after indexing, then cleaned up
        # on every exit path. Callers must supply an isolated checkout.
        with tempfile.TemporaryDirectory(prefix="kms-scip-") as temporary_root:
            temporary_path = Path(temporary_root)
            output_path = temporary_path.joinpath(*relative_index.parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            has_explicit_output = any("{index_path}" in arg for arg in self.indexer_argv)
            default_output_path = root.joinpath(*relative_index.parts)
            if not has_explicit_output and (default_output_path.exists() or default_output_path.is_symlink()):
                raise ScipJobError(
                    "output_exists",
                    f"refusing to overwrite an existing index artifact: {relative_index.as_posix()}",
                )

            command = tuple(
                arg.replace("{repository_root}", str(root)).replace("{index_path}", str(output_path))
                for arg in self.indexer_argv
            )
            # Do not inherit application credentials or unrelated environment
            # variables into a repository indexer process.
            safe_environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": temporary_root,
                "NO_COLOR": "1",
                "CI": "1",
            }
            try:
                self._execute(command, root, "indexer_failed", env=safe_environment)
                if not has_explicit_output:
                    if not default_output_path.is_file() or default_output_path.is_symlink():
                        raise ScipJobError("missing_output", "SCIP indexer did not produce the expected index file")
                    shutil.move(str(default_output_path), str(output_path))
                if not output_path.is_file() or output_path.is_symlink():
                    raise ScipJobError("missing_output", "SCIP indexer did not produce the expected index file")
                if output_path.stat().st_size > self.max_index_bytes:
                    raise ScipJobError("index_too_large", "SCIP index exceeds the configured byte limit")

                with tempfile.TemporaryFile() as stdout_file:
                    decode_command = (*self.scip_cli_argv, "print", "--json", str(output_path))
                    self._execute(
                        decode_command,
                        root,
                        "scip_decode_failed",
                        stdout_file=stdout_file,
                        max_stdout_bytes=self.max_json_bytes,
                        env=safe_environment,
                    )
                    stdout_file.seek(0)
                    payload = stdout_file.read(self.max_json_bytes + 1)
                if len(payload) > self.max_json_bytes:
                    raise ScipJobError("decoded_index_too_large", "decoded SCIP JSON exceeds the configured byte limit")
                try:
                    decoded = json.loads(payload)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ScipJobError("malformed_index", "SCIP CLI returned invalid JSON") from exc
                if not isinstance(decoded, dict):
                    raise ScipJobError("malformed_index", "SCIP CLI output must be a JSON object")
                result = normalize_scip_index(
                    decoded,
                    repository_root=root,
                    source_revision=source_revision,
                    position_encoding_override=self.position_encoding_override,
                )
                if result.indexer_name != self.indexer_name:
                    raise ScipJobError(
                        "indexer_identity_mismatch",
                        f"expected indexer {self.indexer_name!r}, received {result.indexer_name!r}",
                    )
                return result
            finally:
                # Never leave generated SCIP artifacts in the pinned checkout.
                if not has_explicit_output and (default_output_path.exists() or default_output_path.is_symlink()):
                    if default_output_path.is_file() or default_output_path.is_symlink():
                        default_output_path.unlink()

    def _execute(
        self,
        command: Sequence[str],
        cwd: Path,
        failure_status: str,
        *,
        stdout_file=None,
        max_stdout_bytes: int | None = None,
        env: dict[str, str],
    ) -> None:
        """Execute an argument-vector command with timeout and bounded output."""
        with tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    list(command),
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file if stdout_file is not None else subprocess.DEVNULL,
                    stderr=stderr_file,
                )
            except OSError as exc:
                raise ScipJobError("tool_unavailable", f"unable to execute SCIP command: {command[0]}") from exc

            deadline = time.monotonic() + self.timeout_seconds
            while process.poll() is None:
                if max_stdout_bytes is not None and stdout_file is not None:
                    if os.fstat(stdout_file.fileno()).st_size > max_stdout_bytes:
                        process.kill()
                        process.wait()
                        raise ScipJobError("decoded_index_too_large", "decoded SCIP JSON exceeds the configured byte limit")
                if os.fstat(stderr_file.fileno()).st_size > 64 * 1024:
                    process.kill()
                    process.wait()
                    raise ScipJobError("diagnostics_too_large", "SCIP command diagnostics exceeded 64 KiB")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise ScipJobError("timeout", f"SCIP command exceeded {self.timeout_seconds}s")
                time.sleep(0.02)

            if max_stdout_bytes is not None and stdout_file is not None:
                if os.fstat(stdout_file.fileno()).st_size > max_stdout_bytes:
                    raise ScipJobError("decoded_index_too_large", "decoded SCIP JSON exceeds the configured byte limit")
            if os.fstat(stderr_file.fileno()).st_size > 64 * 1024:
                raise ScipJobError("diagnostics_too_large", "SCIP command diagnostics exceeded 64 KiB")
            if process.returncode != 0:
                stderr_file.seek(0)
                diagnostic = stderr_file.read(4096).decode("utf-8", errors="replace")
                raise ScipJobError(failure_status, diagnostic or f"command exited {process.returncode}")


def _get(mapping: dict[str, Any], camel: str, snake: str | None = None, *, default=None):
    """Read a protobuf JSON field using either lowerCamel or snake_case spelling."""
    if camel in mapping:
        return mapping[camel]
    if snake and snake in mapping:
        return mapping[snake]
    return default


def _resolve_project_root(value: str) -> Path:
    """Resolve a SCIP project root encoded as a file URI or absolute path."""
    parsed = urlparse(value)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
    elif parsed.scheme:
        raise ScipJobError("invalid_project_root", "SCIP project root must be a local file URI")
    else:
        path = value
    try:
        return Path(path).resolve(strict=True)
    except OSError as exc:
        raise ScipJobError("invalid_project_root", "SCIP project root does not exist") from exc


def _validated_source_path(root: Path, relative_path: Any) -> Path:
    """Reject non-canonical paths, symlinks, and files outside the checkout."""
    if not isinstance(relative_path, str) or not relative_path:
        raise ScipJobError("invalid_document", "SCIP document path is missing")
    path = PurePosixPath(relative_path)
    windows_path = PureWindowsPath(relative_path)
    if (path.is_absolute() or windows_path.is_absolute() or windows_path.drive
            or "\\" in relative_path or any(part in {"", ".", ".."} for part in relative_path.split("/"))):
        raise ScipJobError("invalid_document", f"non-canonical SCIP document path: {relative_path}")
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ScipJobError("invalid_document", f"SCIP document path contains a symlink: {relative_path}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ScipJobError("invalid_document", f"SCIP document does not exist: {relative_path}") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ScipJobError("invalid_document", f"SCIP document is outside the checkout: {relative_path}")
    return resolved


def _occurrence_range(occurrence: dict[str, Any]) -> tuple[int, int, int, int]:
    """Read typed SCIP ranges, falling back to the deprecated packed range."""
    single = _get(occurrence, "singleLineRange", "single_line_range")
    multi = _get(occurrence, "multiLineRange", "multi_line_range")
    if isinstance(single, dict):
        line = _get(single, "line")
        start = _get(single, "startCharacter", "start_character")
        end = _get(single, "endCharacter", "end_character")
        values = (line, start, line, end)
    elif isinstance(multi, dict):
        values = (
            _get(multi, "startLine", "start_line"),
            _get(multi, "startCharacter", "start_character"),
            _get(multi, "endLine", "end_line"),
            _get(multi, "endCharacter", "end_character"),
        )
    else:
        packed = occurrence.get("range")
        if not isinstance(packed, list) or len(packed) not in {3, 4}:
            raise ScipJobError("invalid_range", "SCIP occurrence has no supported source range")
        values = (packed[0], packed[1], packed[0] if len(packed) == 3 else packed[2], packed[2] if len(packed) == 3 else packed[3])
    if not all(isinstance(value, int) and value >= 0 for value in values):
        raise ScipJobError("invalid_range", "SCIP range coordinates must be non-negative integers")
    if (values[2], values[3]) < (values[0], values[1]):
        raise ScipJobError("invalid_range", "SCIP source range is reversed")
    return values


def _position_to_byte(source: bytes, line: int, character: int, encoding: int) -> int:
    """Convert a SCIP line/character position into a UTF-8 byte offset."""
    lines = source.splitlines(keepends=True)
    if line >= len(lines):
        if line == len(lines) and character == 0 and source.endswith(b"\n"):
            return len(source)
        raise ScipJobError("invalid_range", "SCIP line is outside the source file")
    raw_line = lines[line].rstrip(b"\r\n")
    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScipJobError("invalid_document", "SCIP source file is not valid UTF-8") from exc

    units = 0
    byte_offset = 0
    for character_value in text:
        if units == character:
            return sum(len(item) for item in lines[:line]) + byte_offset
        if encoding == 1:
            units += len(character_value.encode("utf-8"))
        elif encoding == 2:
            units += len(character_value.encode("utf-16-le")) // 2
        else:
            units += 1
        byte_offset += len(character_value.encode("utf-8"))
        if units > character:
            raise ScipJobError("invalid_range", "SCIP character offset splits an encoded character")
    if units == character:
        return sum(len(item) for item in lines[:line]) + byte_offset
    raise ScipJobError("invalid_range", "SCIP character offset is outside the source line")
