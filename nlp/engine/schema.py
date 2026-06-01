# nlp/engine/schema.py
"""
Defines the canonical schema for entities and relations.
This is the contract between NLP and the knowledge graph.
"""

from typing import Literal
from pydantic import BaseModel, Field, field_validator
from uuid import uuid5, NAMESPACE_DNS
import hashlib

EntityType = Literal[
    "PERSON",
    "SYSTEM",
    "TICKET",
    "PROJECT",
    "ENVIRONMENT",
    "FILE",
]

RelationType = Literal[
    "OWNS",
    "MAINTAINS",
    "ASSIGNED_TO",
    "FIXES",
    "DEPLOYED_IN",
    "PART_OF",
]


def deterministic_uuid(entity_type: str, name: str) -> str:
    return str(
        uuid5(
            NAMESPACE_DNS,
            f"{entity_type.lower()}:{name.lower()}",
        )
    )


class Entity(BaseModel):
    text: str
    type: EntityType
    confidence: float = Field(..., ge=0, le=1)

    record_id: str
    source: str
    created_at: str

    @field_validator("text")
    def normalize_text(cls, v):
        return v.strip().lower()

    def to_db_record(self) -> dict:
        entity_id = deterministic_uuid(
            self.type,
            self.text,
        )

        return {
            "id": entity_id,
            "type": self.type.lower(),
            "name": self.text,
            "metadata": {
                "confidence": self.confidence,
                "source": self.source,
                "original_record_id": self.record_id,
                "extracted_at": self.created_at,
            },
            "created_at": self.created_at,
        }


class Relation(BaseModel):
    source: str
    target: str
    type: RelationType

    confidence: float = Field(..., ge=0, le=1)

    record_id: str
    source_type: EntityType
    target_type: EntityType
    created_at: str


def deterministic_edge_id(
    source_id: str,
    target_id: str,
    rel_type: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_DNS,
            f"{source_id}:{rel_type}:{target_id}",
        )
    )
