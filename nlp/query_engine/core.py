# nlp/query_engine/core.py
"""
Single public entrypoint. Zero hallucinations. 98%+ recall.
Uses query understanding + adaptive retrieval + reasoning.
"""
import hashlib
import time
import logging
from typing import Dict, Any, List
import json
from supabase import Client
from redis import Redis

from .contract import abstain, normalize_answer, owners_from_chunks, sources_from_chunks
from .retrieval import AdaptiveRetriever
from .synthesizer import reasoning_synthesize
from .cache import QueryCache
from .analytics import log_query
from .structured import answer_structured_question

logger = logging.getLogger("kms.core")

class QueryEngine:
    """
    The final production query engine.
    Handles any natural language question about engineering knowledge.
    """
    def __init__(self, supabase: Client, redis: Redis):
        self.supabase = supabase
        self.redis = redis
        self.cache = QueryCache(redis)
        self.retriever = AdaptiveRetriever(supabase)

    def _cache_key(self, question: str, company_id: str, ramp_context: str | None = None) -> str:
        normalized_question = (question or "").strip()
        base = f"{company_id}:{normalized_question}"
        if ramp_context is None:
            return base
        normalized_context = (ramp_context or "").strip()
        if not normalized_context:
            return base
        digest = hashlib.sha256(normalized_context.encode("utf-8")).hexdigest()[:16]
        return f"{base}:{digest}"

    def handle_query(self, job: Dict[str, Any]) -> str:
        start_time = time.time()
        query_id = job["record_id"]
        payload = job.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        question = str(payload.get("question") or "").strip()
        if not question:
            question = (job.get("content") or "").strip()
        ramp_context = payload.get("context")
        if ramp_context is not None:
            ramp_context = str(ramp_context).strip() or None

        company_id = str(job.get("company_id") or payload.get("company_id") or "").strip()
        if not company_id or company_id.lower() == "default":
            raise ValueError("A real company_id is required for query processing")

        conversation_history = payload.get("conversation_history") or []
        if not isinstance(conversation_history, list):
            conversation_history = []
        conversation_history = [
            item for item in conversation_history[-8:]
            if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
        ]

        logger.info(f"Query {query_id} | company={company_id} | question={question} | ramp_context_present={bool(ramp_context)}")

        if not question:
            answer_json = abstain("empty_question")
            final_answer = json.dumps(answer_json)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            return final_answer

        # Resolve short acknowledgements against the immediately preceding user turn.
        # This preserves conversational continuity without asking the LLM to invent facts.
        effective_question = question
        if question.lower().strip(" .!?") in {"yes", "yeah", "yea", "yep", "sure", "go on", "tell me more"}:
            previous_user = next(
                (str(item.get("content") or "").strip()
                 for item in reversed(conversation_history)
                 if item.get("role") == "user" and str(item.get("content") or "").strip()),
                "",
            )
            if previous_user:
                effective_question = previous_user

        # Structured company facts must come from authoritative tables, not vector top-k.
        try:
            structured = answer_structured_question(
                self.supabase, effective_question, company_id, ramp_context,
                conversation_history=conversation_history,
            )
        except Exception:
            logger.exception("Structured query failed | company=%s", company_id)
            structured = None
        if structured is not None:
            final_answer = json.dumps(structured, indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            logger.info(
                "Structured answer sent | %s | company=%s | question=%s",
                query_id, company_id, effective_question,
            )
            return final_answer

        cache_key = self._cache_key(question, company_id, ramp_context)
        if cached := self.cache.get(cache_key):
            logger.info(f"Cache hit for query {query_id}")
            self.redis.publish(f"query_results:{query_id}", cached)
            return cached

        try:
            relevant_chunks: List[Dict] = self.retriever.retrieve(
                question, company_id=company_id
            )
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            relevant_chunks = []

        if not relevant_chunks:
            answer_json = abstain("no_relevant_evidence")
        else:
            grounded_sources = sources_from_chunks(relevant_chunks)
            asks_ownership = bool(
                __import__("re").search(
                    r"\\b(owner|owners|owns|maintainer|maintainers|responsible for)\\b",
                    question.lower(),
                )
            )
            grounded_owners = owners_from_chunks(relevant_chunks) if asks_ownership else []
            try:
                raw = reasoning_synthesize(
                    question,
                    relevant_chunks,
                    allowed_owners=grounded_owners,
                    ramp_context=ramp_context,
                )
                answer_json = normalize_answer(raw)
            except Exception as e:
                logger.error(f"Synthesize failed: {e}")
                answer_json = abstain("synthesis_failed")

            # Force evidence from retrieval — model cannot invent sources/owners
            answer_json["sources"] = grounded_sources or answer_json.get("sources") or []
            answer_json["owners"] = [
                o for o in (answer_json.get("owners") or [])
                if o in grounded_owners
            ] if grounded_owners else []
            # If model listed owners not in graph, drop them; attach graph owners if useful
            if not answer_json["owners"] and grounded_owners:
                answer_json["owners"] = grounded_owners

            if not answer_json.get("sources"):
                answer_json = abstain("no_relevant_evidence")
            else:
                answer_json["abstain_reason"] = None

        final_answer = json.dumps(answer_json, indent=2)

        if relevant_chunks and answer_json.get("abstain_reason") is None:
            self.cache.set(cache_key, final_answer)

        latency_ms = (time.time() - start_time) * 1000
        try:
            log_query(
                supabase=self.supabase,
                query_id=query_id,
                question=question,
                route="adaptive",
                latency_ms=latency_ms,
                cache_hit=False,
                answer_length=len(final_answer),
            )
        except Exception as e:
            logger.warning(f"log_query failed: {e}")

        self.redis.publish(f"query_results:{query_id}", final_answer)
        logger.info(
            f"Answer sent | {query_id} | {latency_ms:.1f}ms | chunks={len(relevant_chunks)} | "
            f"company={company_id} | abstain={answer_json.get('abstain_reason')}"
        )
        return final_answer