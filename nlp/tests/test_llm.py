import json
import pytest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from openai import BadRequestError

from engine.llm import llm_infer


@pytest.fixture(autouse=True)
def clear_llm_inference_cache():
    # Each test must exercise its own mocked provider responses.
    llm_infer.cache_clear()
    yield
    llm_infer.cache_clear()


def _json_validation_error():
    return BadRequestError(
        message="Failed to validate JSON",
        response=Mock(),
        body={
            "error": {
                "code": "json_validate_failed",
            }
        },
    )


def test_llm_infer_falls_back_when_groq_json_validation_fails():
    first = _json_validation_error()
    fallback_response = Mock()
    fallback_response.choices = [Mock(message=Mock(content='{"entities": []}'))]

    with patch("engine.llm.client.chat.completions.create", side_effect=[first, fallback_response]) as create:
        llm_infer("Return an object with an entities array.")

    assert create.call_count == 2
    assert "response_format" in create.call_args_list[0].kwargs
    assert "response_format" not in create.call_args_list[1].kwargs


def test_llm_infer_fallback_response_must_be_valid_json():
    first = _json_validation_error()
    fallback_response = Mock()
    fallback_response.choices = [Mock(message=Mock(content="not json"))]

    with patch("engine.llm.client.chat.completions.create", side_effect=[first, fallback_response]):
        try:
            llm_infer("Return an object with an entities array.")
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("Expected invalid fallback JSON to raise")



def test_llm_infer_captures_provider_metadata_and_prompt_version(monkeypatch):
    monkeypatch.setenv("KMS_LLM_PROMPT_VERSION", "answer-v3")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer": "ok"}'))],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=5,
            total_tokens=17,
        ),
    )
    with (
        patch("engine.llm.client.chat.completions.create", return_value=response),
        patch("engine.llm._capture_run") as capture,
    ):
        result = llm_infer("Return an answer.")

    assert result == '{"answer": "ok"}'
    kwargs = capture.call_args.kwargs
    assert kwargs["prompt_version"] == "answer-v3"
    assert kwargs["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
    }
    assert kwargs["status"] == "success"


def test_llm_infer_captures_fallback_provider_response():
    from engine import llm as llm_module

    fallback_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer": "ok"}'))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
    )
    with (
        patch("engine.llm.client.chat.completions.create",
              side_effect=[_json_validation_error(), fallback_response]),
        patch("engine.llm._capture_run") as capture,
    ):
        result = llm_infer("Return an answer.")

    assert result == '{"answer": "ok"}'
    assert capture.call_args.kwargs["usage"]["total_tokens"] == 14
    assert capture.call_args.kwargs["status"] == "success"
