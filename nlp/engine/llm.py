# nlp/engine/llm.py
"""
LLM interface with JSON output.

Uses Groq JSON Object Mode when it succeeds and falls back to a normal
completion if Groq rejects the generated JSON during server-side validation.
"""
import os
import json
import logging
from openai import OpenAI, BadRequestError
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

logger = logging.getLogger("engine.llm")


def _is_json_validation_error(error: BadRequestError) -> bool:
    """Return True only for Groq's model-output JSON validation failure."""
    body = getattr(error, "body", None)
    return isinstance(body, dict) and body.get("code") == "json_validate_failed"


@lru_cache(maxsize=500)
def llm_infer(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 512,
    model: str = "openai/gpt-oss-20b"  # Best Groq model as of Nov 2025
) -> str:
    """Run an LLM request and return its JSON response as a string.

    Groq's JSON Object Mode can reject an otherwise valid request when the
    selected model fails its server-side JSON generation/validation. In that
    specific case, retry once without response_format and rely on the explicit
    JSON-only instruction in the prompt. Other 400 errors are still raised.
    """
    json_prompt = (
        "Return ONLY a valid JSON object. Do not include markdown, code fences, "
        "comments, or explanatory text.\n\n"
        + prompt.strip()
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a deterministic JSON API. Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": json_prompt,
                },
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned an empty response")
        return content.strip()

    except BadRequestError as e:
        if not _is_json_validation_error(e):
            logger.exception("LLM request rejected: %s", e)
            raise

        logger.warning(
            "Groq JSON validation failed for model %s; retrying without response_format",
            model,
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a deterministic JSON API. Return valid JSON only.",
                    },
                    {
                        "role": "user",
                        "content": json_prompt,
                    },
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM fallback returned an empty response")

            content = content.strip()
            json.loads(content)
            return content
        except Exception:
            logger.exception("LLM JSON fallback failed")
            raise

    except Exception as e:
        logger.exception("LLM ERROR: %s", e)
        raise


def fallback_infer(prompt: str, temperature: float, max_tokens: int, model: str) -> str:
    """Compatibility helper for callers that explicitly request plain completion."""
    prompt = prompt.strip() + "\n\nRespond with valid JSON only."
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("LLM fallback returned an empty response")
        content = content.strip()
        json.loads(content)
        return content
    except Exception:
        logger.exception("LLM fallback failed")
        raise
