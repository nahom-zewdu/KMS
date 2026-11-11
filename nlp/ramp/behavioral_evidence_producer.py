"""Typed, provenance-preserving behavioral evidence extraction for Go repositories.

This is an evaluation producer, not a production Ramp or graph integration. It
requires the caller to identify the exact indexed repository revision; it never
substitutes a file's last-commit value for a repository snapshot revision.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

from .evidence_composition import GoEvidenceComposer
from .handler_call_evidence import GoHandlerCallEvidenceExtractor
from .models import Evidence
from .route_evidence import GoRouteEvidenceExtractor


EXTRACTOR_ID = "kms.go.gin.behavioral"
EXTRACTOR_VERSION = "1"


@dataclass(frozen=True)
class SourceProvenance:
    """Source location and extraction context supporting one observation."""

    repository_id: str
    source_revision: str
    extractor_id: str
    extractor_version: str
    source_file: str
    line: int
    observation: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class BehavioralEvidenceRecord:
    """A typed relationship observation with explicit source provenance."""

    ref: str
    evidence_type: str
    subject: str
    object: str
    detail: str
    provenance: tuple[SourceProvenance, ...]


class GoBehavioralEvidenceProducer:
    """Produce bounded route/handler/call evidence from one Go source snapshot.

    The caller must pass a stable repository ID and immutable source revision
    (normally the indexed Git commit SHA). A composed record is marked derived
    from its two directly observed source facts; it does not claim runtime
    execution, interface resolution, branch coverage, or downstream completion.
    """

    LIMITATIONS = (
        "regex-based Go/Gin source extraction; not a Go AST or call-graph analysis",
        "does not resolve interface implementations or runtime dispatch",
        "does not establish that conditional calls execute for every request",
        "does not establish downstream behavior beyond the direct call site",
    )

    def __init__(self) -> None:
        self._routes = GoRouteEvidenceExtractor()
        self._calls = GoHandlerCallEvidenceExtractor()
        self._composer = GoEvidenceComposer()

    def produce(
        self,
        files: Sequence[Mapping[str, str]],
        *,
        repository_id: str,
        source_revision: str,
    ) -> list[BehavioralEvidenceRecord]:
        """Extract primitive and composed records from a single repository revision.

        Each file must provide path and content. Non-Go files are ignored.
        Duplicate paths and missing snapshot identity are rejected so records
        cannot silently mix ambiguous source inputs.
        """
        repository_id = repository_id.strip()
        source_revision = source_revision.strip()
        if not repository_id:
            raise ValueError("repository_id is required")
        if not source_revision:
            raise ValueError("source_revision is required")

        normalized: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        for item in files:
            path = str(item.get("path") or "").strip()
            if not path.endswith(".go"):
                continue
            if path in seen_paths:
                raise ValueError(f"duplicate source path: {path}")
            seen_paths.add(path)
            normalized.append({"path": path, "content": str(item.get("content") or "")})
        normalized.sort(key=lambda item: item["path"])

        routes = self._routes.extract(normalized)
        calls_by_handler: dict[tuple[str, str], list] = {}
        for route in routes:
            key = (route.handler_symbol, route.handler_file)
            if key not in calls_by_handler:
                source = next(
                    item["content"] for item in normalized
                    if item["path"] == route.handler_file
                )
                calls_by_handler[key] = self._calls.extract(
                    source, path=route.handler_file, handler_symbol=route.handler_symbol
                )

        records: list[BehavioralEvidenceRecord] = []
        route_records: dict[tuple[str, str, str, str, int], BehavioralEvidenceRecord] = {}
        call_records: dict[tuple[str, str, str, str, int], BehavioralEvidenceRecord] = {}

        for route in routes:
            provenance = SourceProvenance(
                repository_id=repository_id,
                source_revision=source_revision,
                extractor_id=EXTRACTOR_ID,
                extractor_version=EXTRACTOR_VERSION,
                source_file=route.route_file,
                line=route.line,
                observation="direct",
                limitations=self.LIMITATIONS,
            )
            record = self._record(
                repository_id,
                source_revision,
                "ROUTE_HANDLES",
                f"{route.method} {route.path}",
                route.handler_symbol,
                route.route_file,
                route.line,
                f"{route.method} {route.path} is registered to {route.handler_symbol}",
                (provenance,),
            )
            records.append(record)
            route_records[(route.method, route.path, route.handler_symbol, route.route_file, route.line)] = record

        all_calls = {
            (call.handler_symbol, call.handler_file, call.receiver_field, call.method, call.line): call
            for calls in calls_by_handler.values()
            for call in calls
        }
        for call in sorted(
            all_calls.values(),
            key=lambda item: (item.handler_file, item.line, item.handler_symbol, item.receiver_field, item.method),
        ):
            provenance = SourceProvenance(
                repository_id=repository_id,
                source_revision=source_revision,
                extractor_id=EXTRACTOR_ID,
                extractor_version=EXTRACTOR_VERSION,
                source_file=call.handler_file,
                line=call.line,
                observation="direct",
                limitations=self.LIMITATIONS,
            )
            target = f"{call.receiver_field}.{call.method}"
            record = self._record(
                repository_id, source_revision, "HANDLER_INVOKES",
                call.handler_symbol, target, call.handler_file, call.line,
                f"{call.handler_symbol} directly calls {target}",
                (provenance,),
            )
            records.append(record)
            call_records[(call.handler_symbol, call.handler_file, call.receiver_field, call.method, call.line)] = record

        composed = self._composer.compose(routes, list(all_calls.values()))
        for item in composed:
            route_record = route_records[
                (item.method, item.path, item.handler_symbol, item.route_file, item.route_line)
            ]
            call_record = call_records[
                (item.handler_symbol, item.call_file, item.receiver_field, item.operation, item.call_line)
            ]
            records.append(
                self._record(
                    repository_id,
                    source_revision,
                    "ROUTE_HANDLER_OPERATION",
                    f"{item.method} {item.path}",
                    item.next_inspection_target,
                    item.route_file,
                    item.route_line,
                    (
                        f"{item.method} {item.path} is registered to {item.handler_symbol}, "
                        f"which directly calls {item.next_inspection_target}"
                    ),
                    (route_record.provenance[0], call_record.provenance[0]),
                    observation="derived",
                )
            )

        return sorted(records, key=lambda item: (item.evidence_type, item.ref))

    @staticmethod
    def _record(
        repository_id: str,
        source_revision: str,
        evidence_type: str,
        subject: str,
        target: str,
        source_file: str,
        line: int,
        detail: str,
        provenance: tuple[SourceProvenance, ...],
        *,
        observation: str = "direct",
    ) -> BehavioralEvidenceRecord:
        """Build a stable record ID and provenance-preserving typed record."""
        normalized_provenance = tuple(
            SourceProvenance(
                repository_id=item.repository_id,
                source_revision=item.source_revision,
                extractor_id=item.extractor_id,
                extractor_version=item.extractor_version,
                source_file=item.source_file,
                line=item.line,
                observation=observation,
                limitations=item.limitations,
            )
            for item in provenance
        )
        identity = "|".join(
            [
                repository_id,
                source_revision,
                evidence_type,
                subject,
                target,
                source_file,
                str(line),
            ]
        )
        ref = "behavior:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return BehavioralEvidenceRecord(
            ref=ref,
            evidence_type=evidence_type,
            subject=subject,
            object=target,
            detail=detail,
            provenance=normalized_provenance,
        )


def to_workflow_evidence(
    records: Sequence[BehavioralEvidenceRecord],
) -> list[Evidence]:
    """Adapt composed observations to Ramp's in-memory evidence contract.

    Only route -> handler -> direct-operation compositions become graph-shaped
    workflow evidence. Primitive route/call observations remain available to
    evaluators but are not promoted to file-to-file workflow relationships.
    This adapter is intentionally in-memory; it does not imply DB persistence.
    """
    result: list[Evidence] = []
    for record in records:
        if record.evidence_type != "ROUTE_HANDLER_OPERATION":
            continue
        if len(record.provenance) != 2:
            continue

        route, call = record.provenance
        if (
            route.repository_id != call.repository_id
            or route.source_revision != call.source_revision
            or route.extractor_id != call.extractor_id
            or route.extractor_version != call.extractor_version
            or not route.source_file
            or not call.source_file
            or route.line < 1
            or call.line < 1
        ):
            continue

        provenance = {
            "repository_id": route.repository_id,
            "source_revision": route.source_revision,
            "extractor_id": route.extractor_id,
            "extractor_version": route.extractor_version,
            "source_file": route.source_file,
            "line": route.line,
            "observation": "derived",
            "call_source_file": call.source_file,
            "call_line": call.line,
            "call_observation": "direct",
            "limitations": list(route.limitations),
        }
        result.append(
            Evidence(
                ref=record.ref,
                source=route.extractor_id,
                kind="implementation_relation",
                strength="derived",
                detail=record.detail,
                repository_id=route.repository_id,
                metadata={
                    "source_ref": route.source_file,
                    "target_ref": call.source_file,
                    "relation_type": record.evidence_type,
                    "provenance": provenance,
                },
            )
        )
    return sorted(result, key=lambda item: item.ref)
