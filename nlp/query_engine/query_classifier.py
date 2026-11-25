"""Conservative, deterministic classification for repository knowledge queries.

The classifier is deliberately side-effect free. It does not infer authorization
scope, resolve symbols, access conversation storage, or execute retrieval.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .query_plan import (
    PlanDisposition,
    QueryIntent,
    QueryPlan,
    QueryScope,
)


_COURTESY = {
    "thanks", "thank you", "thx", "you're welcome", "you are welcome",
    "hello", "hi", "hey", "good morning", "good afternoon",
}
_CLARIFICATION = {
    "what", "huh", "what?", "huh?", "which one", "which one?",
    "can you clarify", "could you clarify", "please clarify",
}
_FOLLOW_UP_PREFIXES = (
    "what about ", "how about ", "and ", "also ", "why is that",
    "why does that", "how does that", "can you explain that",
    "explain that", "tell me more", "go on",
)
_STRUCTURED_PATTERNS = (
    re.compile(r"\b(owner|owners|owns|maintainer|maintainers|responsible for)\b", re.I),
    re.compile(r"\b(who|which person)\b.*\b(implemented|authored|wrote|changed|committed)\b", re.I),
    re.compile(r"\b(how many|count|number of)\b.*\b(files?|source files?|steps?|tasks?|repositories|repos)\b", re.I),
    re.compile(r"\b(what is the repo|which repo|where are we right now)\b", re.I),
)
_CALL_SITE_PATTERNS = (
    re.compile(r"\b(call sites? of|usages? of|references? to|where is .+ called|where .+ is called)\b", re.I),
    re.compile(r"\b(who calls|what calls|find calls to)\b", re.I),
)
_DECLARATION_PATTERNS = (
    re.compile(r"\b(where is|where's) .+ (defined|declared)\b", re.I),
    re.compile(r"\b(definition|declaration) of\b", re.I),
    re.compile(r"\b(find|locate|show) (the )?(function|method|class|symbol|constant)\b", re.I),
    re.compile(r"\b(which file|what file) (defines|contains)\b", re.I),
)
_PASSAGE_CUES = re.compile(
    r"\b(explain|describe|how does|how do|what happens|why does|"
    r"trace|walk me through|workflow|flow|implementation|logic|"
    r"code|function|method|class|module|file|repository|repo|"
    r"bug|error|exception|test|api|endpoint|handler)\b",
    re.I,
)
_PATH_RE = re.compile(
    r"(?<![\w.])(?:[\w.-]+/)+[\w.-]+\.(?:py|pyi|go|js|jsx|ts|tsx|java|kt|rs|rb|php|sql|yaml|yml|toml|json)(?::\d+(?:-\d+)?)?",
    re.I,
)
_QUALIFIED_RE = re.compile(r"(?<![\w/])(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*(?![\w/])")
_BACKTICK_RE = re.compile(r"`([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)`")
_IDENTIFIER_RE = re.compile(r"(?<![\w])(?:[A-Za-z_]\w{2,})(?![\w])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "does", "for",
    "from", "how", "into", "is", "its", "please", "show", "that",
    "the", "their", "there", "this", "through", "what", "where",
    "which", "with", "would", "you",
}


def _normalized(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip().lower().rstrip(" .!?")


def _has_context(history: Sequence[Mapping[str, object]]) -> bool:
    return any(
        item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
        and item["content"].strip()
        for item in history[-8:]
    )


def _extract(query: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    paths = tuple(dict.fromkeys(_PATH_RE.findall(query)))[:50]
    qualified = tuple(dict.fromkeys(_QUALIFIED_RE.findall(query)))[:50]
    explicit = _BACKTICK_RE.findall(query)
    identifiers = tuple(dict.fromkeys(
        [*explicit, *[value for value in _IDENTIFIER_RE.findall(query) if value not in qualified]]
    ))[:50]
    terms = tuple(dict.fromkeys(
        word.lower() for word in _WORD_RE.findall(query)
        if word.lower() not in _STOP_WORDS
    ))[:20]
    return terms, paths, identifiers, qualified


def classify_query(
    query: str,
    scope: QueryScope,
    conversation_history: Sequence[Mapping[str, object]] = (),
) -> QueryPlan:
    """Return a bounded typed plan using conservative lexical rules.

    `scope` must come from trusted caller context. Conversation history is
    inspected only to distinguish a follow-up from an unresolved fragment; no
    prior message or evidence identifier is fabricated or resolved.
    """
    if not isinstance(scope, QueryScope):
        raise ValueError("scope must be a trusted QueryScope")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(conversation_history, Sequence) or isinstance(
        conversation_history, (str, bytes)
    ):
        raise ValueError("conversation_history must be a sequence of message mappings")

    history = tuple(
        item for item in conversation_history[-8:]
        if isinstance(item, Mapping)
    )
    normalized = _normalized(query)
    terms, paths, identifiers, qualified = _extract(query)

    common = {
        "query": query.strip(),
        "scope": scope,
        "terms": terms,
        "file_paths": paths,
        "identifiers": identifiers,
        "qualified_names": qualified,
    }

    if normalized in _COURTESY:
        return QueryPlan(intent=QueryIntent.COURTESY, **common)

    if normalized in _CLARIFICATION or len(normalized.split()) <= 2 and normalized.endswith("?"):
        return QueryPlan(
            intent=QueryIntent.CLARIFICATION,
            disposition=PlanDisposition.NEEDS_CLARIFICATION,
            ambiguity_reason="The current turn does not identify what should be clarified.",
            **common,
        )

    if normalized.startswith(_FOLLOW_UP_PREFIXES):
        if _has_context(history):
            return QueryPlan(intent=QueryIntent.FOLLOW_UP, **common)
        return QueryPlan(
            intent=QueryIntent.CLARIFICATION,
            disposition=PlanDisposition.NEEDS_CLARIFICATION,
            ambiguity_reason="This appears to refer to earlier context, but no usable conversation history was supplied.",
            **common,
        )

    if any(pattern.search(query) for pattern in _STRUCTURED_PATTERNS):
        intent = QueryIntent.STRUCTURED_FACT
    elif any(pattern.search(query) for pattern in _CALL_SITE_PATTERNS):
        intent = QueryIntent.CALL_SITE_NAVIGATION
    elif any(pattern.search(query) for pattern in _DECLARATION_PATTERNS):
        intent = QueryIntent.DECLARATION_DISCOVERY
    elif _PASSAGE_CUES.search(query):
        intent = QueryIntent.PASSAGE_RETRIEVAL
    else:
        return QueryPlan(
            intent=QueryIntent.UNSUPPORTED,
            disposition=PlanDisposition.ABSTAIN,
            abstention_reason="No supported repository-knowledge intent could be identified conservatively.",
            **common,
        )

    return QueryPlan(intent=intent, **common)
