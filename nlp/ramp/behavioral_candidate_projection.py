"""Read-only projection of composed behavioral evidence into evaluation units.

This module intentionally stops before production Ramp planning. It converts
route -> handler -> direct-operation observations into bounded evidence units
for quality evaluation only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .evidence_composition import ComposedRouteEvidence


@dataclass(frozen=True)
class BehavioralCandidateEvidence:
    """One bounded behavioral evidence unit suitable for evaluation."""

    candidate_id: str
    method: str
    path: str
    handler_symbol: str
    handler_file: str
    operation: str
    receiver_field: str
    call_file: str
    call_line: int
    route_file: str
    route_line: int
    next_inspection_target: str

    @property
    def evidence_type(self) -> str:
        """Return the stable evidence type used by this evaluation layer."""
        return "ROUTE_HANDLER_DIRECT_OPERATION"

    @property
    def behavior_statement(self) -> str:
        """Describe only the source facts established by the evidence."""
        return (
            f"{self.method} {self.path} is registered to "
            f"{self.handler_symbol}, which directly calls "
            f"{self.next_inspection_target}."
        )


class GoBehavioralCandidateProjector:
    """Project composed route evidence without adding behavioral inference."""

    def project(
        self, evidence: Sequence[ComposedRouteEvidence]
    ) -> list[BehavioralCandidateEvidence]:
        """Return deterministic, one-to-one behavioral evidence units.

        The projector does not resolve implementations, infer runtime order,
        merge branches, assign ownership, or persist candidates.
        """
        projected: list[BehavioralCandidateEvidence] = []
        for item in evidence:
            candidate_id = (
                f"behavior:{item.method.lower()}:{item.path}:"
                f"{item.handler_symbol}:{item.receiver_field}:{item.operation}"
            )
            projected.append(
                BehavioralCandidateEvidence(
                    candidate_id=candidate_id,
                    method=item.method,
                    path=item.path,
                    handler_symbol=item.handler_symbol,
                    handler_file=item.handler_file,
                    operation=item.operation,
                    receiver_field=item.receiver_field,
                    call_file=item.call_file,
                    call_line=item.call_line,
                    route_file=item.route_file,
                    route_line=item.route_line,
                    next_inspection_target=item.next_inspection_target,
                )
            )

        return sorted(
            projected,
            key=lambda item: (
                item.method,
                item.path,
                item.handler_symbol,
                item.receiver_field,
                item.operation,
                item.call_line,
            ),
        )
