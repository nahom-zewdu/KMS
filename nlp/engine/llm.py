# nlp/engine/llm.py
"""
LLM interface with caching, retry, and schema validation.
"""
import os
import json
import time
from typing import Any, Dict, List
from openai import OpenAI
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

@lru_cache(maxsize=500)
def llm_infer(prompt: str, temperature: float = 0.0, max_tokens: int = 512 ,  model: str = "llama-3.1-8b-instant") -> str:
    """
    High-precision LLM inference with JSON enforcement.
    Model: llama-3.1-70b-versatile (current Groq flagship, Nov 2025)
    """
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(0.5 * (2 ** attempt))
    return "[]"

def parse_json_response(response: str) -> List[Dict]:
    """Safely parse JSON from LLM output."""
    try:
        # Find JSON array
        start = response.find("[")
        end = response.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        json_str = response[start:end]
        return json.loads(json_str)
    except:
        return []
    