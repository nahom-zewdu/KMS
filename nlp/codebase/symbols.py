"""Syntax-aware, revision-pinned symbol extraction for supported source files.

The extractor emits declarations only. It does not resolve references, infer
runtime behavior, or persist graph relationships; those require separate,
explicit evidence producers.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Iterable

from tree_sitter import Language, Parser
import tree_sitter_go
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript


EXTRACTOR_VERSION = "1"
_LANGUAGE_BINDINGS = {
    "Python": ("python", tree_sitter_python.language),
    "Go": ("go", tree_sitter_go.language),
    "JavaScript": ("javascript", tree_sitter_javascript.language),
    "TypeScript": ("typescript", tree_sitter_typescript.language_typescript),
    "TSX": ("tsx", tree_sitter_typescript.language_tsx),
}
_EXTENSION_LANGUAGES = {
    ".py": "Python",
    ".go": "Go",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".tsx": "TSX",
}


@dataclass(frozen=True)
class CodeSymbol:
    """A source declaration with stable identity and immutable source provenance."""

    symbol_id: str
    repository_id: str
    file_path: str
    language: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    content_hash: str
    source_revision: str
    extractor_version: str = EXTRACTOR_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the symbol."""
        return asdict(self)


@dataclass(frozen=True)
class SymbolExtraction:
    """The declarations and parser status for one immutable source file."""

    file_path: str
    language: str
    source_revision: str
    content_hash: str
    has_syntax_errors: bool
    symbols: tuple[CodeSymbol, ...]


class CodeSymbolExtractor:
    """Extract stable declarations from Python, Go, JavaScript, TypeScript, and TSX."""

    SUPPORTED_LANGUAGES = frozenset(_LANGUAGE_BINDINGS)

    def extract_file(
        self,
        *,
        repository_id: str,
        file_path: str,
        source: str,
        source_revision: str,
        language: str | None = None,
    ) -> SymbolExtraction | None:
        """Parse one source file and return declarations pinned to its commit.

        Unsupported languages and empty revisions are rejected by returning
        None; callers must not silently label unparsed files as indexed.
        """
        resolved_language = language or self._language_for_path(file_path)
        if resolved_language not in _LANGUAGE_BINDINGS or not source_revision:
            return None

        _grammar_name, grammar_factory = _LANGUAGE_BINDINGS[resolved_language]
        parser = Parser(Language(grammar_factory()))
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
        if tree is None:
            return None

        content_hash = hashlib.sha256(source_bytes).hexdigest()
        symbols = self._extract_declarations(
            tree.root_node,
            source_bytes,
            repository_id=repository_id,
            file_path=file_path,
            language=resolved_language,
            source_revision=source_revision,
            content_hash=content_hash,
        )
        return SymbolExtraction(
            file_path=file_path,
            language=resolved_language,
            source_revision=source_revision,
            content_hash=content_hash,
            has_syntax_errors=tree.root_node.has_error,
            symbols=tuple(symbols),
        )

    def extract_files(
        self,
        files: Iterable[dict[str, str]],
        *,
        repository_id: str,
        source_revision: str,
    ) -> list[SymbolExtraction]:
        """Extract supported files deterministically from a repository inventory."""
        results = []
        for item in sorted(files, key=lambda value: value.get("path", "")):
            result = self.extract_file(
                repository_id=repository_id,
                file_path=item.get("path", ""),
                source=item.get("content", ""),
                source_revision=source_revision,
                language=item.get("language"),
            )
            if result is not None:
                results.append(result)
        return results

    @staticmethod
    def _language_for_path(file_path: str) -> str | None:
        """Resolve a supported language from the source file extension."""
        return _EXTENSION_LANGUAGES.get(PurePosixPath(file_path).suffix.lower())

    def _extract_declarations(
        self,
        root,
        source: bytes,
        *,
        repository_id: str,
        file_path: str,
        language: str,
        source_revision: str,
        content_hash: str,
    ) -> list[CodeSymbol]:
        """Walk declaration nodes and retain their exact source byte/line spans."""
        declarations = {
            "Python": {
                "function_definition": "function",
                "class_definition": "class",
            },
            "Go": {
                "function_declaration": "function",
                "method_declaration": "method",
                "type_spec": "type",
            },
            "JavaScript": {
                "function_declaration": "function",
                "class_declaration": "class",
                "method_definition": "method",
            },
            "TypeScript": {
                "function_declaration": "function",
                "class_declaration": "class",
                "interface_declaration": "interface",
                "type_alias_declaration": "type",
                "enum_declaration": "enum",
                "method_definition": "method",
                "method_signature": "method",
            },
            "TSX": {
                "function_declaration": "function",
                "class_declaration": "class",
                "interface_declaration": "interface",
                "type_alias_declaration": "type",
                "enum_declaration": "enum",
                "method_definition": "method",
                "method_signature": "method",
            },
        }[language]

        output: list[CodeSymbol] = []
        stack = [root]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.children))
            kind = declarations.get(node.type)
            if not kind:
                continue

            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
            if not name:
                continue

            declaration_node = node
            if language == "Python" and node.parent and node.parent.type == "decorated_definition":
                declaration_node = node.parent

            if language == "Python" and kind == "function" and self._is_python_method(node):
                kind = "method"
            qualified_name = self._qualified_name(
                node, name, source, kind=kind
            )
            if language == "Go" and kind == "method":
                receiver = node.child_by_field_name("receiver")
                receiver_name = self._first_type_name(receiver, source) if receiver else None
                if receiver_name:
                    qualified_name = f"{receiver_name}.{name}"
            if language == "Go" and kind == "type":
                type_node = node.child_by_field_name("type")
                if type_node and type_node.type in {"struct_type", "interface_type"}:
                    kind = "struct" if type_node.type == "struct_type" else "interface"

            identity = "\0".join((
                repository_id, file_path, language, kind, qualified_name,
                str(declaration_node.start_byte),
            ))
            symbol_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            output.append(
                CodeSymbol(
                    symbol_id=symbol_id,
                    repository_id=repository_id,
                    file_path=file_path,
                    language=language,
                    name=name,
                    qualified_name=qualified_name,
                    kind=kind,
                    start_line=declaration_node.start_point.row + 1,
                    end_line=declaration_node.end_point.row + 1,
                    start_byte=declaration_node.start_byte,
                    end_byte=declaration_node.end_byte,
                    content_hash=content_hash,
                    source_revision=source_revision,
                )
            )

        return sorted(output, key=lambda item: (item.start_byte, item.end_byte, item.qualified_name))

    @staticmethod
    def _is_python_method(node) -> bool:
        """Return true only when a function is directly scoped by a class body."""
        parent = node.parent
        while parent is not None:
            if parent.type in {"function_definition", "lambda"}:
                return False
            if parent.type == "class_definition":
                return True
            parent = parent.parent
        return False

    @staticmethod
    def _qualified_name(node, name: str, source: bytes, *, kind: str) -> str:
        """Qualify methods with their nearest enclosing class or interface."""
        if kind != "method":
            return name
        parent = node.parent
        while parent is not None:
            if parent.type in {"class_definition", "class_declaration", "interface_declaration"}:
                name_node = parent.child_by_field_name("name")
                if name_node is not None:
                    parent_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                    return f"{parent_name}.{name}"
            parent = parent.parent
        return name

    @staticmethod
    def _first_type_name(node, source: bytes) -> str | None:
        """Find the declared receiver type without resolving aliases or interfaces."""
        if node is None:
            return None
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type in {"type_identifier", "identifier"}:
                return source[current.start_byte:current.end_byte].decode("utf-8")
            stack.extend(reversed(current.children))
        return None
