# nlp/engine/llm.py
"""
LLM interface with enforced JSON output.
Works perfectly with Groq + response_format.
"""
import os
import json
import time
import logging
from typing import Any
from openai import OpenAI
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

logger = logging.getLogger("engine.llm")

@lru_cache(maxsize=500)
def llm_infer(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 512,
    model: str = "llama-3.1-8b-instant"  # Best Groq model as of Nov 2025
) -> str:
    """
    Always returns valid JSON string when response_format is used.
    Works because prompt contains 'json' → satisfies Groq requirement.
    """
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.exception(f"LLM ERROR: {e}")
            raise
    return '{"error": "llm_failed"}'

def fallback_infer(prompt: str, temperature: float, max_tokens: int, model: str) -> str:
    """Last resort: ask for JSON in prompt"""
    prompt = prompt.strip() + "\n\nRespond with valid JSON only."
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        return resp.choices[0].message.content.strip()
    except:
        return '{"answer": "I could not process that request."}'
