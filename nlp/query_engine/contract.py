# nlp/query_engine/contract.py
"""
Canonical query answer contract for KMS.
All query paths must return this shape. No free-form prose at the boundary.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


ABSTAIN_NO_EVIDENCE = {
    "answer": "Not enough indexed company data to answer that yet.",
    "confidence": "low",
    "sources": [],
    "owners": [],
    "abstain_reason": "no_relevant_evidence",
}


def normalize_answer(payload: Any) -> Dict[str, Any]:
    """
    Coerce model/string output into the canonical contract.
    Never invent owners or sources.
    """
    if isinstance(payload, str):
        text = payload.strip()
        try:
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:].strip()
            payload = json.loads(text)
        except Exception:
            return {
                "answer": text[:500] if text else ABSTAIN_NO_EVIDENCE["answer"],
                "confidence": "low",
                "sources": [],
                "owners": [],
                "abstain_reason": "unstructured_model_output",
            }

    if not isinstance(payload, dict):
        return dict(ABSTAIN_NO_EVIDENCE)

    answer = str(payload.get("answer") or "").strip()
    confidence = str(payload.get("confidence") or "medium").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    sources = _normalize_sources(payload.get("sources"))
    owners = _normalize_owners(payload.get("owners"))
    abstain = payload.get("abstain_reason")
    if abstain is not None:
        abstain = str(abstain).strip() or None

    if not answer:
        return dict(ABSTAIN_NO_EVIDENCE)

    # If model claimed facts but gave no sources, downgrade
    if not sources and confidence == "high":
        confidence = "medium"

    return {
        "answer": answer,
        "confidence": confidence,
        "sources": sources,
        "owners": owners,
        "abstain_reason": abstain,
    }


def abstain(reason: str = "no_relevant_evidence") -> Dict[str, Any]:
    out = dict(ABSTAIN_NO_EVIDENCE)
    out["abstain_reason"] = reason
    return out


def _normalize_sources(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not raw:
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append({"source": "unknown", "record_id": item.strip()[:64]})
            elif isinstance(item, dict):
                src = str(item.get("source") or "unknown")[:32]
                rid = str(item.get("record_id") or item.get("id") or "")[:64]
                fpath = str(item.get("file_path") or "")[:200]
                entry = {"source": src, "record_id": rid}
                if fpath:
                    entry["file_path"] = fpath
                if rid or fpath:
                    out.append(entry)
    return out[:8]


def _normalize_owners(raw: Any) -> List[str]:
    if not raw:
        return []
    names: List[str] = []
    if isinstance(raw, list):
        for x in raw:
            n = str(x).strip()
            if n and n.lower() not in ("unknown", "none", "n/a") and n not in names:
                names.append(n)
    return names[:5]


def sources_from_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Derive sources only from retrieved chunks (never LLM)."""
    out: List[Dict[str, str]] = []
    seen = set()
    for c in chunks:
        src = str(c.get("source") or "raw")
        rid = str(c.get("record_id") or "")[:64]
        key = (src, rid, c.get("content", "")[:40])
        if key in seen:
            continue
        seen.add(key)
        entry = {"source": src, "record_id": rid}
        if c.get("file_path"):
            entry["file_path"] = str(c["file_path"])[:200]
        out.append(entry)
        if len(out) >= 8:
            break
    return out


def owners_from_chunks(chunks: List[Dict[str, Any]]) -> List[str]:
    """Extract person-like owners only from graph edge text / explicit fields."""
    owners: List[str] = []
    for c in chunks:
        if c.get("owners") and isinstance(c["owners"], list):
            for o in c["owners"]:
                n = str(o).strip()
                if n and n not in owners:
                    owners.append(n)
        content = (c.get("content") or "").strip()
        # "alice OWNS billing" / "alice MAINTAINS auth"
        parts = content.split()
        if len(parts) >= 3 and parts[1].upper() in (
            "OWNS",
            "MAINTAINS",
            "ASSIGNED_TO",
            "FIXES",
        ):
            name = parts[0].strip()
            if name and name.lower() != "unknown" and name not in owners:
                owners.append(name)
    return owners[:5]
