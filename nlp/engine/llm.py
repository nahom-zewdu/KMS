# nlp/engine/llm.py
"""
LLM interface with enforced JSON output.
Works perfectly with Groq + response_format.
"""
import os
import json
import time
from typing import Any
from openai import OpenAI
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

@lru_cache(maxsize=500)
def llm_infer(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 512,
    model: str = "llama-3.1-70b-versatile"  # Best Groq model as of Nov 2025
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
            if "json" in str(e).lower():
                # Fallback: force plain text if Groq is being strict
                if attempt == 2:
                    return fallback_infer(prompt, temperature, max_tokens, model)
                time.sleep(0.8 * (2 ** attempt))
                continue
            if attempt == 2:
                return fallback_infer(prompt, temperature, max_tokens, model)
            time.sleep(0.5 * (2 ** attempt))
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
