# nlp/engine/schema.py
"""
Defines the canonical schema for entities and relations.
This is the contract between NLP and the knowledge graph.
"""
from typing import Literal, List
from pydantic import BaseModel, Field, validator
from datetime import datetime

EntityType = Literal["PERSON", "SYSTEM", "TICKET", "PROJECT", "ENVIRONMENT"]
RelationType = Literal["OWNS", "MAINTAINS", "ASSIGNED_TO", "FIXES", "DEPLOYED_IN", "PART_OF"]

class Entity(BaseModel):
    text: str = Field(..., description="Exact text span")
    type: EntityType = Field(..., description="Canonical type")
    confidence: float = Field(..., ge=0, le=1)
    record_id: str
    source: str
    created_at: str  # ISO format

    @validator("text")
    def normalize_text(cls, v):
        return v.strip().lower()

class Relation(BaseModel):
    source: str = Field(..., description="Source entity text")
    target: str = Field(..., description="Target entity text")
    type: RelationType = Field(..., description="Canonical relation")
    confidence: float = Field(..., ge=0, le=1)
    record_id: str
    source_type: EntityType
    target_type: EntityType
    created_at: str