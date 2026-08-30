import json
from unittest.mock import Mock, patch

from openai import BadRequestError

from engine.llm import llm_infer


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
