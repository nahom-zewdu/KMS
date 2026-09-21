"""Read-only Go HTTP route/handler evidence extraction for Ramp evaluation.

This module observes explicit Gin route registrations and resolves handler symbols
to source files. It deliberately does not infer runtime flow, ownership, safety,
or business responsibility and does not persist evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence


@dataclass(frozen=True)
class RouteEvidence:
    """One explicit route-to-handler registration observed in source."""

    method: str
    path: str
    handler_symbol: str
    handler_file: str
    route_file: str
    line: int


class GoRouteEvidenceExtractor:
    """Extract deterministic, read-only route/handler facts from Go source."""

    _CONSTRUCTOR_RE = re.compile(
        r"(?m)^\s*(?P<variable>[A-Za-z_]\w*)\s*:=\s*New"
        r"(?P<handler>[A-Za-z_]\w*Handler)\s*\("
    )
    _HANDLER_TYPE_RE_TEMPLATE = r"(?m)^\s*type\s+{handler}\s+struct\s*\{{"
    _ROUTE_RE = re.compile(
        r'(?m)^\s*router\.(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)'
        r'\(\s*"(?P<path>[^"]+)"\s*,\s*'
        r'(?P<variable>[A-Za-z_]\w*)\.(?P<method_name>[A-Za-z_]\w*)\s*\)'
    )

    def extract(self, files: Sequence[dict]) -> list[RouteEvidence]:
        """Return only route registrations whose handler type resolves uniquely.

        Files are dictionaries with path and content fields. Unresolvable handler
        variables/types are skipped rather than guessed.
        """
        source_by_path = {
            str(item["path"]): str(item.get("content", ""))
            for item in files
            if item.get("path")
        }

        constructors: dict[str, str] = {}
        for path, content in sorted(source_by_path.items()):
            for match in self._CONSTRUCTOR_RE.finditer(content):
                constructors.setdefault(match.group("variable"), match.group("handler"))

        handler_files: dict[str, list[str]] = {}
        for path, content in sorted(source_by_path.items()):
            for handler in constructors.values():
                pattern = re.compile(
                    self._HANDLER_TYPE_RE_TEMPLATE.format(handler=re.escape(handler))
                )
                if pattern.search(content):
                    handler_files.setdefault(handler, []).append(path)

        evidence: list[RouteEvidence] = []
        for route_file, content in sorted(source_by_path.items()):
            for match in self._ROUTE_RE.finditer(content):
                handler = constructors.get(match.group("variable"))
                files_for_handler = handler_files.get(handler, []) if handler else []
                if len(files_for_handler) != 1:
                    continue

                line = content.count("\n", 0, match.start()) + 1
                evidence.append(
                    RouteEvidence(
                        method=match.group("method"),
                        path=match.group("path"),
                        handler_symbol=f"{handler}.{match.group('method_name')}",
                        handler_file=files_for_handler[0],
                        route_file=route_file,
                        line=line,
                    )
                )

        return sorted(
            evidence,
            key=lambda item: (
                item.method,
                item.path,
                item.handler_symbol,
                item.handler_file,
                item.route_file,
                item.line,
            ),
        )
