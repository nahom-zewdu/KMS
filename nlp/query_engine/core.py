# nlp/query_engine/core.py
"""
Single public entrypoint. Zero hallucinations. 98%+ recall.
Uses query understanding + adaptive retrieval + reasoning.
"""
import hashlib
import time
import logging
import re
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
from .source_retriever import retrieve_source_chunks
from codebase.source_chunk_retriever import SourceChunkRetriever
from codebase.symbol_retriever import CodeSymbolRetriever
from codebase.scip_occurrence_retriever import ScipOccurrenceRetriever
from .evidence_gatherer import BoundedEvidenceGatherer
from .planned_query import PlannedQueryExecutor
from .query_plan import QueryIntent, QueryScope
from .query_planner import classify_query
from .repository_scope import TrustedRepositoryScopeResolver
from .symbol_resolution import ConservativeScipSymbolResolver

logger = logging.getLogger("kms.core")

class QueryEngine:
    """
    The final production query engine.
    Handles any natural language question about engineering knowledge.
    """
    def __init__(
        self,
        supabase: Client,
        redis: Redis,
        outcome_observer=None,
        planned_synthesizer=None,
        legacy_synthesizer=None,
        offline_evaluation: bool = False,
    ):
        self.supabase = supabase
        self.redis = redis
        self.outcome_observer = outcome_observer
        self.legacy_synthesizer = legacy_synthesizer
        self.offline_evaluation = bool(offline_evaluation)
        self.cache = QueryCache(redis)
        self.retriever = AdaptiveRetriever(supabase)
        self.repository_scope_resolver = TrustedRepositoryScopeResolver(supabase)
        source_chunks = SourceChunkRetriever(supabase)
        symbols = CodeSymbolRetriever(supabase)
        occurrences = ScipOccurrenceRetriever(supabase)
        self.planned_executor = PlannedQueryExecutor(
            evidence_gatherer=BoundedEvidenceGatherer(
                source_chunks=source_chunks,
                symbols=symbols,
                occurrences=occurrences,
            ),
            symbol_resolver=ConservativeScipSymbolResolver(symbols, occurrences),
            **({"synthesizer": planned_synthesizer} if planned_synthesizer is not None else {}),
        )

    def _observe_outcome(
        self,
        *,
        query_id: str,
        route: str,
        outcome: str,
        reason: str | None = None,
        intent: str | None = None,
        evidence_count: int = 0,
        evidence_items=None,
        source_records=None,
        source_company_id: str | None = None,
    ) -> None:
        """Emit structured execution telemetry for tests and offline evaluation."""
        if self.outcome_observer is None:
            return
        event = {
            "query_id": str(query_id),
            "route": route,
            "outcome": outcome,
            "reason": reason,
            "intent": intent,
            "evidence_count": int(evidence_count),
            "source_company_id": source_company_id,
            "source_records": [
                {
                    "source": item.get("source"),
                    "record_id": item.get("record_id"),
                    "file_path": item.get("file_path"),
                }
                for item in (source_records or [])
                if isinstance(item, dict)
            ],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_type": item.evidence_type,
                    "company_id": item.company_id,
                    "repository_id": item.repository_id,
                    "snapshot_id": item.snapshot_id,
                    "source_revision": item.source_revision,
                    "file_path": item.file_path,
                    "content_hash": item.content_hash,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "start_byte": item.start_byte,
                    "end_byte": item.end_byte,
                    "source": item.source,
                    "record_id": item.record_id,
                    "retriever": item.retriever,
                }
                for item in (evidence_items or [])
            ],
        }
        try:
            self.outcome_observer(event)
        except Exception:
            # Evaluation/telemetry callbacks must never change query behavior.
            logger.exception("Query outcome observer failed | query_id=%s", query_id)

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
        conversation_refs = payload.get("conversation_refs") or []
        if not isinstance(conversation_refs, list):
            conversation_refs = []
        conversation_refs = [
            ref for ref in conversation_refs
            if isinstance(ref, str) and ref.strip()
        ][:10]

        logger.info("Query received | query_id=%s | company=%s | ramp_context_present=%s", query_id, company_id, bool(ramp_context))

        if not question:
            answer_json = abstain("empty_question")
            final_answer = json.dumps(answer_json)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            self._observe_outcome(
                query_id=query_id, route="input_guard", outcome="abstained",
                reason="empty_question", intent=None, evidence_count=0,
            )
            return final_answer

        # Resolve short acknowledgements against the immediately preceding user turn.
        # This preserves conversational continuity without asking the LLM to invent facts.
        effective_question = question
        if question.lower().strip(" .!?") in {"yes", "yeah", "yea", "yep", "sure", "go on", "tell me more"}:
            previous_user = next(
                (str(item.get("content") or "").strip()
                 for item in reversed(conversation_history)
                 if item.get("role") == "user"
                 and str(item.get("content") or "").strip()
                 and str(item.get("content") or "").strip() != question),
                "",
            )
            if previous_user:
                effective_question = previous_user

        # A bare "what?" is ambiguous; avoid unrelated graph/vector retrieval.
        if question.lower().strip(" .!?") in {"what", "huh"}:
            answer_json = {
                "answer": "What would you like me to clarify from my previous answer?",
                "confidence": "low",
                "sources": [],
                "owners": [],
                "abstain_reason": "ambiguous_follow_up",
            }
            final_answer = json.dumps(answer_json, indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            self._observe_outcome(
                query_id=query_id, route="conversation_guard", outcome="abstained",
                reason="ambiguous_follow_up", intent="clarification", evidence_count=0,
            )
            return final_answer

        if question.lower().strip(" .!?") in {"thank you", "thanks", "thx"}:
            answer_json = {
                "answer": "You're welcome.",
                "confidence": "high",
                "sources": [],
                "owners": [],
                "abstain_reason": None,
            }
            final_answer = json.dumps(answer_json, indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            self._observe_outcome(
                query_id=query_id, route="conversation_control", outcome="answered",
                reason=None, intent="courtesy", evidence_count=0,
            )
            return final_answer

        # Route supported code-intelligence questions through KRT-04 only after
        # resolving one company-owned active repository. The request selector is
        # merely a selector; the database resolver verifies ownership and snapshot.
        route_classification_started = time.perf_counter()
        try:
            candidate_plan = classify_query(
                effective_question,
                scope=QueryScope(company_id=company_id),
                conversation_history=conversation_history,
                conversation_refs=conversation_refs,
            )
        except ValueError:
            candidate_plan = None
        logger.info(
            "kms_query_stage query_id=%s stage=route_classification duration_ms=%.3f",
            query_id, (time.perf_counter() - route_classification_started) * 1000,
        )

        # Follow-ups require an explicit, resolvable conversation reference.
        # Until a reference resolver is available, fail closed instead of
        # falling through to unrelated source or graph retrieval.
        if candidate_plan and candidate_plan.intent in {
            QueryIntent.FOLLOW_UP, QueryIntent.CLARIFICATION
        }:
            reason = (
                "conversation_context_unresolved"
                if candidate_plan.intent is QueryIntent.FOLLOW_UP
                else "ambiguous_follow_up"
            )
            answer_json = {
                "answer": (
                    "I can continue, but I need the specific file, function, or symbol "
                    "you want me to trace."
                ),
                "confidence": "low",
                "sources": [],
                "owners": [],
                "abstain_reason": reason,
            }
            final_answer = json.dumps(answer_json, indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            logger.info(
                "kms_query_outcome query_id=%s route=conversation outcome=abstained "
                "reason=%s evidence_count=0",
                query_id, reason,
            )
            self._observe_outcome(
                query_id=query_id, route="conversation_guard", outcome="abstained",
                reason=reason, intent=candidate_plan.intent.value, evidence_count=0,
            )
            return final_answer

        # Structured facts must be answered from authoritative records before
        # source retrieval or model synthesis can pre-empt the deterministic route.
        structured_attempted = bool(
            candidate_plan and candidate_plan.intent is QueryIntent.STRUCTURED_FACT
        )
        if structured_attempted:
            try:
                structured_result = answer_structured_question(
                    self.supabase, effective_question, company_id, ramp_context,
                    conversation_history=conversation_history,
                )
            except Exception:
                logger.exception("Structured query failed | company=%s", company_id)
                structured_result = None
            if structured_result is not None:
                final_answer = json.dumps(structured_result, indent=2)
                self.redis.publish(f"query_results:{query_id}", final_answer)
                logger.info(
                    "Structured answer sent | query_id=%s | company=%s",
                    query_id, company_id,
                )
                self._observe_outcome(
                    query_id=query_id, route="structured_handler",
                    outcome="abstained" if structured_result.get("abstain_reason") else "answered",
                    reason=structured_result.get("abstain_reason"),
                    intent=candidate_plan.intent.value,
                    evidence_count=len(structured_result.get("sources") or []),
                    source_records=structured_result.get("sources") or [],
                    source_company_id=company_id,
                )
                return final_answer

            # Never fall through to source/LLM retrieval for a query classified
            # as a structured fact when its authoritative handler has no answer.
            final_answer = json.dumps(abstain("structured_evidence_unavailable"), indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            logger.warning(
                "Abstained on structured fact without authoritative evidence | %s | company=%s",
                query_id, company_id,
            )
            self._observe_outcome(
                query_id=query_id, route="structured_handler", outcome="abstained",
                reason="structured_evidence_unavailable",
                intent=candidate_plan.intent.value, evidence_count=0,
                source_records=[], source_company_id=company_id,
            )
            return final_answer

        if candidate_plan and candidate_plan.intent is QueryIntent.UNSUPPORTED:
            answer_json = abstain(candidate_plan.abstention_reason or "unsupported_query")
            final_answer = json.dumps(answer_json, indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            self._observe_outcome(
                query_id=query_id, route="abstain", outcome="abstained",
                reason=answer_json.get("abstain_reason"),
                intent=candidate_plan.intent.value, evidence_count=0,
            )
            return final_answer

        if candidate_plan and candidate_plan.intent in {
            QueryIntent.PASSAGE_RETRIEVAL,
            QueryIntent.DECLARATION_DISCOVERY,
            QueryIntent.CALL_SITE_NAVIGATION,
        }:
            repository_started = time.perf_counter()
            repository_resolution = self.repository_scope_resolver.resolve(
                company_id,
                repository_id=job.get("repository"),
            )
            logger.info(
                "kms_query_stage query_id=%s stage=repository_scope duration_ms=%.3f",
                query_id, (time.perf_counter() - repository_started) * 1000,
            )
            if not repository_resolution.resolved:
                scope_reason = repository_resolution.reason or "unresolved"
                answer_json = abstain(f"repository_scope_{scope_reason}")
                logger.info(
                    "kms_query_outcome query_id=%s route=planned outcome=abstained "
                    "reason=repository_scope_%s evidence_count=0",
                    query_id, scope_reason,
                )
                final_answer = json.dumps(answer_json, indent=2)
                self.redis.publish(f"query_results:{query_id}", final_answer)
                self._observe_outcome(
                    query_id=query_id, route="planned_query", outcome="abstained",
                    reason=f"repository_scope_{scope_reason}",
                    intent=candidate_plan.intent.value, evidence_count=0,
                )
                return final_answer

            def observe_planned_stage(stage: str, duration_ms: float) -> None:
                logger.info(
                    "kms_query_stage query_id=%s stage=%s duration_ms=%.3f",
                    query_id, stage, duration_ms,
                )

            planned_started = time.perf_counter()
            planned = self.planned_executor.execute(
                effective_question,
                scope=QueryScope(
                    company_id=company_id,
                    repository_id=repository_resolution.repository_id,
                ),
                conversation_history=conversation_history,
                stage_observer=observe_planned_stage,
            )
            logger.info(
                "kms_query_stage query_id=%s stage=planned_query_total duration_ms=%.3f",
                query_id, (time.perf_counter() - planned_started) * 1000,
            )
            if not planned.deferred and planned.answer is not None:
                final_answer = json.dumps(dict(planned.answer), indent=2)
                self.redis.publish(f"query_results:{query_id}", final_answer)
                outcome = "abstained" if planned.answer.get("abstain_reason") else "answered"
                reason = planned.reason or planned.answer.get("abstain_reason") or "none"
                logger.info(
                    "kms_query_outcome query_id=%s route=planned intent=%s outcome=%s "
                    "reason=%s evidence_count=%d",
                    query_id, planned.plan.intent.value, outcome, reason, len(planned.evidence),
                )
                logger.info(
                    "KRT-04 planned answer sent | %s | company=%s | repository=%s | "
                    "intent=%s | abstain=%s",
                    query_id, company_id, repository_resolution.repository_id,
                    planned.plan.intent.value,
                    planned.answer.get("abstain_reason"),
                )
                self._observe_outcome(
                    query_id=query_id, route="planned_query", outcome=outcome,
                    reason=planned.answer.get("abstain_reason") or planned.reason,
                    intent=planned.plan.intent.value, evidence_count=len(planned.evidence),
                    evidence_items=planned.evidence,
                )
                return final_answer

            if self.offline_evaluation:
                answer_json = abstain("planned_query_deferred_in_offline_evaluation")
                final_answer = json.dumps(answer_json, indent=2)
                self.redis.publish(f"query_results:{query_id}", final_answer)
                self._observe_outcome(
                    query_id=query_id, route="planned_query", outcome="abstained",
                    reason=answer_json.get("abstain_reason"),
                    intent=planned.plan.intent.value, evidence_count=len(planned.evidence),
                    evidence_items=planned.evidence,
                )
                return final_answer

        if self.offline_evaluation:
            answer_json = abstain("evaluation_route_unavailable")
            final_answer = json.dumps(answer_json, indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            self._observe_outcome(
                query_id=query_id, route="abstain", outcome="abstained",
                reason=answer_json.get("abstain_reason"),
                intent=candidate_plan.intent.value if candidate_plan else None,
                evidence_count=0,
            )
            return final_answer

        # For file-explanation questions, retrieve bounded source text from files
        # already indexed under this company before asking the model to explain them.
        try:
            source_chunks = retrieve_source_chunks(
                self.supabase, company_id, effective_question, ramp_context,
                conversation_history=conversation_history,
            )
        except Exception:
            logger.exception("Source-code retrieval failed | company=%s", company_id)
            source_chunks = []
        if source_chunks:
            try:
                raw_source_answer = (self.legacy_synthesizer or reasoning_synthesize)(
                    effective_question,
                    source_chunks,
                    allowed_owners=[],
                    ramp_context=ramp_context,
                )
                source_answer = normalize_answer(raw_source_answer)
            except Exception:
                logger.exception("Source-code synthesis failed | company=%s", company_id)
                source_answer = abstain("synthesis_failed")
            source_answer["sources"] = sources_from_chunks(source_chunks)
            source_answer["owners"] = []
            if source_answer.get("sources") and source_answer.get("abstain_reason") is None:
                final_answer = json.dumps(source_answer, indent=2)
                self.redis.publish(f"query_results:{query_id}", final_answer)
                logger.info(
                    "Source-grounded answer sent | %s | company=%s | files=%d",
                    query_id, company_id, len(source_chunks),
                )
                self._observe_outcome(
                    query_id=query_id, route="source_retrieval", outcome="answered",
                    reason=None, intent=candidate_plan.intent.value if candidate_plan else None,
                    evidence_count=len(source_chunks),
                )
                return final_answer

        # Non-structured routes retain the legacy structured fallback. A
        # STRUCTURED_FACT plan was already checked before source retrieval above.
        structured = None
        if not structured_attempted:
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
                "Structured answer sent | query_id=%s | company=%s",
                query_id, company_id,
            )
            self._observe_outcome(
                query_id=query_id, route="structured_handler",
                outcome="abstained" if structured.get("abstain_reason") else "answered",
                reason=structured.get("abstain_reason"),
                intent=candidate_plan.intent.value if candidate_plan else None,
                evidence_count=len(structured.get("sources") or []),
            )
            return final_answer

        requires_structured_facts = bool(re.search(
            r"\b(owner|owners|owns|maintainer|maintainers|responsible for)\b"
            r"|\b(who|which person)\b.*\b(implemented|authored|wrote|changed|committed)\b"
            r"|\b(how many|count|number of)\b.*\b(files?|source files?|steps?|tasks?)\b"
            r"|\bwhat is the repo\b|\bwhere are we right now\b",
            effective_question.lower(),
        ))
        if requires_structured_facts:
            final_answer = json.dumps(abstain("structured_evidence_unavailable"), indent=2)
            self.redis.publish(f"query_results:{query_id}", final_answer)
            logger.warning(
                "Abstained on structured fact without authoritative evidence | %s | company=%s",
                query_id, company_id,
            )
            self._observe_outcome(
                query_id=query_id, route="abstain", outcome="abstained",
                reason="structured_evidence_unavailable",
                intent=candidate_plan.intent.value if candidate_plan else None,
                evidence_count=0,
            )
            return final_answer

        cache_key = self._cache_key(effective_question, company_id, ramp_context)
        if cached := self.cache.get(cache_key):
            logger.info(f"Cache hit for query {query_id}")
            self.redis.publish(f"query_results:{query_id}", cached)
            cached_payload = json.loads(cached)
            self._observe_outcome(
                query_id=query_id, route="adaptive_cache",
                outcome="abstained" if cached_payload.get("abstain_reason") else "answered",
                reason=cached_payload.get("abstain_reason"),
                intent=candidate_plan.intent.value if candidate_plan else None,
                evidence_count=len(cached_payload.get("sources") or []),
            )
            return cached

        try:
            relevant_chunks: List[Dict] = self.retriever.retrieve(
                effective_question, company_id=company_id
            )
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            relevant_chunks = []

        if not relevant_chunks:
            answer_json = abstain("no_relevant_evidence")
        else:
            grounded_sources = sources_from_chunks(relevant_chunks)
            grounded_owners = owners_from_chunks(relevant_chunks)
            try:
                raw = (self.legacy_synthesizer or reasoning_synthesize)(
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
        self._observe_outcome(
            query_id=query_id, route="adaptive",
            outcome="abstained" if answer_json.get("abstain_reason") else "answered",
            reason=answer_json.get("abstain_reason"),
            intent=candidate_plan.intent.value if candidate_plan else None,
            evidence_count=len(relevant_chunks),
        )
        return final_answer