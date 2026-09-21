"""Read-only Go handler -> direct dependency-call evidence for Ramp evaluation.

This module observes explicit calls from an HTTP handler method through fields
declared on that handler's struct. It does not resolve interfaces, infer
implementations, construct a call graph, or persist evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class HandlerCallEvidence:
    """One direct handler-field method call observed in source."""

    handler_symbol: str
    receiver_field: str
    method: str
    handler_file: str
    line: int


class GoHandlerCallEvidenceExtractor:
    """Extract deterministic, read-only direct dependency calls from Go handlers."""

    _METHOD_RE = re.compile(
        r"(?m)^\s*func\s*\(\s*h\s+\*?(?P<handler>[A-Za-z_]\w*)\s*\)"
        r"\s*(?P<method>[A-Za-z_]\w*)\s*\("
    )
    _STRUCT_RE_TEMPLATE = r"(?m)^\s*type\s+{handler}\s+struct\s*\{{"
    _FIELD_RE = re.compile(
        r"(?m)^\s*(?P<field>[A-Za-z_]\w*)\s+(?P<type>[^\n/]+?)(?:\s+//.*)?$"
    )
    _CALL_RE = re.compile(
        r"\bh\.(?P<field>[A-Za-z_]\w*)\.(?P<method>[A-Za-z_]\w*)\s*\("
    )

    def extract(
        self, content: str, *, path: str, handler_symbol: str
    ) -> list[HandlerCallEvidence]:
        """Return direct calls through fields declared on the target handler.

        handler_symbol must be of the form Type.Method. If the target method
        or handler struct cannot be resolved, the extractor abstains.
        Interface implementations and arbitrary package/function calls are not
        resolved.
        """
        try:
            handler_name, method_name = handler_symbol.split(".", 1)
        except ValueError:
            return []

        struct_match = re.search(
            self._STRUCT_RE_TEMPLATE.format(handler=re.escape(handler_name)),
            content,
        )
        if not struct_match:
            return []

        struct_end = self._find_matching_brace(content, struct_match.end() - 1)
        if struct_end is None:
            return []

        fields = {
            match.group("field")
            for match in self._FIELD_RE.finditer(
                content[struct_match.end() : struct_end]
            )
        }
        if not fields:
            return []

        target = None
        for match in self._METHOD_RE.finditer(content):
            if (
                match.group("handler") == handler_name
                and match.group("method") == method_name
            ):
                target = match
                break
        if target is None:
            return []

        body_start = content.find("{", target.end())
        if body_start == -1:
            return []
        body_end = self._find_matching_brace(content, body_start)
        if body_end is None:
            return []

        body = content[body_start + 1 : body_end]
        evidence: list[HandlerCallEvidence] = []
        for match in self._CALL_RE.finditer(body):
            field = match.group("field")
            if field not in fields:
                continue
            line = content.count("\n", 0, body_start + 1 + match.start()) + 1
            evidence.append(
                HandlerCallEvidence(
                    handler_symbol=handler_symbol,
                    receiver_field=field,
                    method=match.group("method"),
                    handler_file=path,
                    line=line,
                )
            )

        return evidence

    @staticmethod
    def _find_matching_brace(content: str, opening_index: int) -> int | None:
        """Find a matching brace with lightweight string/comment awareness."""
        depth = 0
        i = opening_index
        state = "code"
        while i < len(content):
            char = content[i]
            next_char = content[i + 1] if i + 1 < len(content) else ""

            if state == "code":
                if char == '"':
                    state = "string"
                elif char == "'":
                    state = "rune"
                elif char == "/" and next_char == "/":
                    state = "line_comment"
                    i += 1
                elif char == "/" and next_char == "*":
                    state = "block_comment"
                    i += 1
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return i
            elif state == "string":
                if char == "\\":
                    i += 1
                elif char == '"':
                    state = "code"
            elif state == "rune":
                if char == "\\":
                    i += 1
                elif char == "'":
                    state = "code"
            elif state == "line_comment":
                if char == "\n":
                    state = "code"
            elif state == "block_comment" and char == "*" and next_char == "/":
                state = "code"
                i += 1

            i += 1

        return None
