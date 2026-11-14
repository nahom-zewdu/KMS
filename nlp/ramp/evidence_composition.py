"""Read-only composition of Go route, handler, and direct-call evidence.

This module joins independently observed source facts into a bounded onboarding
boundary. It does not infer runtime workflows, concrete interface
implementations, ownership, safety, or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .handler_call_evidence import HandlerCallEvidence
from .route_evidence import RouteEvidence


@dataclass(frozen=True)
class ComposedRouteEvidence:
    """One route → handler → direct dependency operation observation."""

    method: str
    path: str
    handler_symbol: str
    handler_file: str
    route_file: str
    route_line: int
    receiver_field: str
    operation: str
    call_file: str
    call_line: int

    @property
    def next_inspection_target(self) -> str:
        """Return the directly observed operation to inspect next."""
        return f"{self.receiver_field}.{self.operation}"


class GoEvidenceComposer:
    """Compose only route and handler-call facts sharing a handler symbol/file."""

    def compose(
        self,
        routes: Sequence[RouteEvidence],
        calls: Sequence[HandlerCallEvidence],
    ) -> list[ComposedRouteEvidence]:
        """Join matching route and direct-call observations deterministically.

        A route is composed only with calls from the same handler symbol and
        handler source file. Missing calls remain absent rather than being
        guessed or synthesized.
        """
        calls_by_handler: dict[tuple[str, str], list[HandlerCallEvidence]] = {}
        for call in calls:
            key = (call.handler_symbol, call.handler_file)
            calls_by_handler.setdefault(key, []).append(call)

        evidence: list[ComposedRouteEvidence] = []
        for route in routes:
            key = (route.handler_symbol, route.handler_file)
            for call in calls_by_handler.get(key, []):
                evidence.append(
                    ComposedRouteEvidence(
                        method=route.method,
                        path=route.path,
                        handler_symbol=route.handler_symbol,
                        handler_file=route.handler_file,
                        route_file=route.route_file,
                        route_line=route.line,
                        receiver_field=call.receiver_field,
                        operation=call.method,
                        call_file=call.handler_file,
                        call_line=call.line,
                    )
                )

        return sorted(
            evidence,
            key=lambda item: (
                item.method,
                item.path,
                item.handler_symbol,
                item.route_file,
                item.route_line,
                item.call_line,
                item.receiver_field,
                item.operation,
            ),
        )
