"""Deterministic, conservative query classification and plan construction.

The classifier uses bounded lexical signals only. It does not infer authorization
scope, resolve symbols, execute retrieval, or call external services.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .query_plan import (
    MAX_CONVERSATION_REFS, MAX_IDENTIFIER_COUNT, MAX_PATH_COUNT, MAX_TERM_COUNT,
    PlanDisposition, QueryIntent, QueryPlan, QueryScope,
)

_COURTESY = {"thanks", "thank you", "thx", "hello", "hi", "hey",
             "good morning", "good afternoon", "good evening"}
_ACKNOWLEDGEMENTS = {"yes", "yeah", "yea", "yep", "sure", "go on", "tell me more"}
_BARE_CLARIFICATIONS = {"what", "huh", "which one", "what do you mean"}
_FOLLOW_UP_START = re.compile(
    r"^(?:and|also|what about|how about|show me more|tell me more)\b", re.IGNORECASE)
_FOLLOW_UP_REFERENCE = re.compile(
    r"\b(?:it|that|this|they|them|those|the same one|the previous one)\b"
    r"(?!\s+(?:company|organization|repository|repo|project|codebase|file|"
    r"function|class|method|symbol|branch|plan|ramp|step|task|question|"
    r"query|team|user|engineer)\b)",
    re.IGNORECASE,
)
_CALL_SITE = re.compile(
    r"\b(?:where\s+(?:is|are)\s+.+\s+called|who\s+calls|call\s+sites?|"
    r"callers?\s+of|references?\s+to|find\s+(?:all\s+)?calls\s+to)\b", re.IGNORECASE)
_DECLARATION = re.compile(
    r"\b(?:where\s+(?:is|are)\s+.+\s+defined|(?:find|locate|show)\s+(?:the\s+)?"
    r"(?:definition|declaration|function|class|method|symbol)|definition\s+of|"
    r"declaration\s+of)\b", re.IGNORECASE)
_STRUCTURED = re.compile(
    r"\b(?:how\s+many|count|number\s+of|who\s+(?:owns|is responsible)|owner|owners|"
    r"maintainer|maintainers|repository\s+metadata|repo(?:sitory)?\s+"
    r"(?:name|url|default branch)|when\s+was\s+.+\s+(?:created|updated))\b",
    re.IGNORECASE)
_PASSAGE = re.compile(
    r"\b(?:explain|how\s+does|how\s+do|walk\s+me\s+through|what\s+does|"
    r"show\s+me\s+(?:the\s+)?(?:code|implementation)|where\s+is\s+.+\s+implemented|"
    r"trace\s+.+)\b", re.IGNORECASE)
_ENGINEERING_CONTEXT = re.compile(
    r"\b(?:code|codebase|repository|repo|file|function|class|method|module|api|"
    r"endpoint|handler|service|database|query|commit|pull request|bug|error|test|"
    r"implementation|workflow|symbol)\b", re.IGNORECASE)
_PATH = re.compile(
    r"(?<![\w.-])(?:[\w@.+-]+/)*[\w@.+-]+\."
    r"(?:py|pyi|go|js|jsx|ts|tsx|java|rs|rb|php|sql|yaml|yml|json|toml|md)"
    r"(?![\w-]|\.(?=\w))", re.IGNORECASE)
_BACKTICK = re.compile(r"\x60([^\x60]{1,256})\x60")
_QUALIFIED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w{1,255}\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,199}")
_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "can", "could", "does",
    "explain", "find", "for", "from", "give", "have", "help", "how", "into",
    "is", "its", "locate", "me", "more", "please", "show", "tell", "that",
    "the", "this", "through", "to", "trace", "what", "where", "which", "who",
    "why", "with",
}


def _normalized(query: str) -> str:
    return " ".join(query.strip().lower().split()).strip(" .!?,")


def _unique_bounded(values: Iterable[str], limit: int) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
            if len(result) == limit:
                break
    return tuple(result)


def _extract(
    query: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    paths = _unique_bounded(_PATH.findall(query), MAX_PATH_COUNT)
    path_keys = {path.casefold() for path in paths}
    qualified = _unique_bounded(
        (value for value in _QUALIFIED.findall(query) if value.casefold() not in path_keys),
        MAX_IDENTIFIER_COUNT,
    )
    explicit = [match.group(1).strip() for match in _BACKTICK.finditer(query)]
    path_tokens = {
        part.casefold()
        for path in paths
        for part in re.split(r"[/\\.]", path)
        if part
    }
    identifiers = _unique_bounded(
        [
            *explicit,
            *qualified,
            *(
                token for token in _IDENTIFIER.findall(query)
                if token.casefold() not in path_tokens
                and ("_" in token or any(char.isupper() for char in token[1:]))
            ),
        ],
        MAX_IDENTIFIER_COUNT,
    )
    terms = _unique_bounded(
        (word for word in _WORD.findall(query) if word.casefold() not in _STOP_WORDS),
        MAX_TERM_COUNT)
    return terms, paths, identifiers, qualified


def _history_available(history: Sequence[Mapping[str, object]] | None) -> bool:
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        return False
    return any(
        item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
        and bool(str(item.get("content")).strip())
        for item in history[-8:] if isinstance(item, Mapping)
    )


def classify_query(
    query: str,
    *,
    scope: QueryScope,
    conversation_history: Sequence[Mapping[str, object]] | None = None,
    conversation_refs: Sequence[str] = (),
) -> QueryPlan:
    """Classify a query without guessing missing context or resolving symbols.

    Scope must come from trusted caller context. Conversation references are
    accepted only when supplied by the caller; this function never invents IDs.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(scope, QueryScope):
        raise ValueError("scope must be a trusted QueryScope")
    if not isinstance(conversation_refs, Sequence) or isinstance(conversation_refs, (str, bytes)):
        raise ValueError("conversation_refs must be a sequence of strings")
    if any(not isinstance(ref, str) for ref in conversation_refs):
        raise ValueError("conversation_refs must contain only strings")

    normalized = _normalized(query)
    history_exists = _history_available(conversation_history)
    refs = _unique_bounded(conversation_refs, MAX_CONVERSATION_REFS)
    terms, paths, identifiers, qualified = _extract(query)

    if normalized in _COURTESY:
        intent, disposition = QueryIntent.COURTESY, PlanDisposition.READY
    elif normalized in _BARE_CLARIFICATIONS:
        intent, disposition = QueryIntent.CLARIFICATION, PlanDisposition.NEEDS_CLARIFICATION
    elif normalized in _ACKNOWLEDGEMENTS or _FOLLOW_UP_START.search(query) or (
        _FOLLOW_UP_REFERENCE.search(query)
        and not (_ENGINEERING_CONTEXT.search(query) or paths or identifiers)
    ):
        if history_exists and refs:
            intent, disposition = QueryIntent.FOLLOW_UP, PlanDisposition.READY
        else:
            intent, disposition = QueryIntent.CLARIFICATION, PlanDisposition.NEEDS_CLARIFICATION
    elif _CALL_SITE.search(query):
        intent, disposition = QueryIntent.CALL_SITE_NAVIGATION, PlanDisposition.READY
    elif _DECLARATION.search(query):
        intent, disposition = QueryIntent.DECLARATION_DISCOVERY, PlanDisposition.READY
    elif _STRUCTURED.search(query):
        intent, disposition = QueryIntent.STRUCTURED_FACT, PlanDisposition.READY
    elif _PASSAGE.search(query) and (_ENGINEERING_CONTEXT.search(query) or paths or identifiers):
        intent, disposition = QueryIntent.PASSAGE_RETRIEVAL, PlanDisposition.READY
    elif _ENGINEERING_CONTEXT.search(query) or paths or identifiers:
        intent, disposition = QueryIntent.PASSAGE_RETRIEVAL, PlanDisposition.READY
    else:
        intent, disposition = QueryIntent.UNSUPPORTED, PlanDisposition.ABSTAIN

    ambiguity_reason = None
    abstention_reason = None
    if disposition is PlanDisposition.NEEDS_CLARIFICATION:
        ambiguity_reason = (
            "The follow-up does not have a caller-supplied conversation reference."
            if history_exists or normalized in _ACKNOWLEDGEMENTS
            else "The request is too ambiguous to route safely.")
    elif disposition is PlanDisposition.ABSTAIN:
        abstention_reason = "unsupported_query"

    return QueryPlan(
        query=query, intent=intent, scope=scope, disposition=disposition,
        terms=terms, file_paths=paths, identifiers=identifiers,
        qualified_names=qualified,
        conversation_refs=refs if intent is QueryIntent.FOLLOW_UP else (),
        ambiguity_reason=ambiguity_reason, abstention_reason=abstention_reason,
    )
