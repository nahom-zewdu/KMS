# nlp/query_engine/graph/patterns.py
"""
Predefined high-precision graph traversal patterns.

These patterns are pure SQL + Python templating.
They execute in <50ms and never hallucinate because they only return facts that exist in the graph.
"""
from typing import List, Dict, Any
from datetime import datetime

GRAPH_PATTERNS = {
    "who_owns": {
        "question_keywords": ["who owns", "owner of", "owns", "responsible for", "maintains"],
        "sql": """
            WITH target AS (
                SELECT id FROM entities 
                WHERE lower(name) = lower(%(entity)s) 
                  AND type IN ('SYSTEM', 'PROJECT', 'SERVICE', 'REPO')
                  AND active = true
                LIMIT 1
            ),
            owners AS (
                SELECT 
                    e.source_id,
                    e.confidence,
                    e.last_seen_at
                FROM edges e
                JOIN target t ON e.target_id = t.id
                WHERE e.type = 'OWNS'
                  AND e.confidence >= 0.8
                  AND (e.expires_at IS NULL OR e.expires_at > now())
            )
            SELECT 
                ent.name,
                ent.type,
                o.confidence,
                o.last_seen_at
            FROM owners o
            JOIN entities ent ON o.source_id = ent.id
            WHERE ent.type = 'PERSON'
            ORDER BY o.confidence DESC, o.last_seen_at DESC
            LIMIT 3
        """,
        "template": "{name} owns {entity} (confidence: {confidence:.0%})",
    },

    "what_does_person_own": {
        "question_keywords": ["what does", "owns", "maintains", "responsible for"],
        "sql": """
            SELECT 
                target.name as entity_name,
                target.type,
                e.confidence
            FROM edges e
            JOIN entities person ON e.source_id = person.id
            JOIN entities target ON e.target_id = target.id
            WHERE lower(person.name) = lower(%(person)s)
              AND person.type = 'PERSON'
              AND e.type = 'OWNS'
              AND e.confidence >= 0.7
              AND (e.expires_at IS NULL OR e.expires_at > now())
              AND target.active = true
            ORDER BY e.confidence DESC
            LIMIT 5
        """,
        "template": "{person} owns {entity_name}",
    },

    "who_fixed": {
        "question_keywords": ["who fixed", "fixed", "who resolved", "resolved"],
        "sql": """
            WITH ticket AS (
                SELECT id FROM entities 
                WHERE (name = %(ticket)s OR lower(name) LIKE lower(%(ticket)s))
                  AND type = 'TICKET'
                LIMIT 1
            )
            SELECT 
                p.name,
                e.confidence
            FROM edges e
            JOIN entities p ON e.source_id = p.id
            JOIN ticket t ON e.target_id = t.id
            WHERE e.type IN ('FIXES', 'RESOLVED')
              AND p.type = 'PERSON'
            ORDER BY e.confidence DESC
            LIMIT 3
        """,
        "template": "{name} fixed {ticket}",
    }
}
