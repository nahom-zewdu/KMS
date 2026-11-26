from __future__ import annotations

import json

from evaluation.run_capture import record_llm_run


def test_capture_is_disabled_without_explicit_path(monkeypatch):
    monkeypatch.delenv("KMS_LLM_RUN_CAPTURE_PATH", raising=False)

    assert not record_llm_run(
        prompt="private prompt",
        output="private answer",
        model="model-a",
        prompt_version="unit-v2",
        temperature=0.0,
        max_tokens=100,
        duration_ms=12.3,
        status="success",
    )


def test_capture_writes_hashes_and_metadata_without_content(tmp_path, monkeypatch):
    path = tmp_path / "runs.jsonl"
    monkeypatch.setenv("KMS_LLM_RUN_CAPTURE_PATH", str(path))

    assert record_llm_run(
        prompt="private prompt text",
        output="private generated answer",
        model="model-a",
        temperature=0.0,
        max_tokens=100,
        duration_ms=12.3456,
        status="success",
        usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["model"] == "model-a"
    assert record["prompt_version"] == "unit-v2"
    assert path.stat().st_mode & 0o777 == 0o600
    assert record["duration_ms"] == 12.346
    assert record["usage"] == {
        "prompt_tokens": 20,
        "completion_tokens": 8,
        "total_tokens": 28,
    }
    assert record["prompt_sha256"]
    assert record["output_sha256"]
    assert "private prompt text" not in path.read_text(encoding="utf-8")
    assert "private generated answer" not in path.read_text(encoding="utf-8")


def test_capture_ignores_unrecognized_or_invalid_usage(tmp_path, monkeypatch):
    path = tmp_path / "runs.jsonl"
    monkeypatch.setenv("KMS_LLM_RUN_CAPTURE_PATH", str(path))

    record_llm_run(
        prompt="p",
        output=None,
        model="model-a",
        temperature=0,
        max_tokens=50,
        duration_ms=1,
        status="error",
        usage={"prompt_tokens": -1, "secret": "must-not-be-captured"},
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["usage"] == {}
    assert record["output_sha256"] is None
