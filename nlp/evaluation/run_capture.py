"""Opt-in, content-free LLM run metadata capture for local evaluation.

Set KMS_LLM_RUN_CAPTURE_PATH to explicitly enable JSONL capture. Prompts,
responses, credentials, and source text are never written to the artifact.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


def _digest(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_llm_run(
    *,
    prompt: str,
    output: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    duration_ms: float,
    status: str,
    usage: Mapping[str, Any] | None = None,
) -> bool:
    """Append one sanitized record when capture is explicitly enabled.

    Returns False when disabled. The configured path is treated as a local
    artifact destination; no directories are created implicitly.
    """
    configured_path = os.getenv("KMS_LLM_RUN_CAPTURE_PATH", "").strip()
    if not configured_path:
        return False

    safe_usage: dict[str, int] = {}
    if usage:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                safe_usage[key] = value

    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model)[:128],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "duration_ms": round(max(0.0, float(duration_ms)), 3),
        "status": str(status)[:32],
        "prompt_sha256": _digest(prompt),
        "output_sha256": _digest(output),
        "usage": safe_usage,
    }
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path = Path(configured_path).expanduser()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    return True
