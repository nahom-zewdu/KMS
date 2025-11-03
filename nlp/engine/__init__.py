# engine/__init__.py
from .schema import Entity, Relation, EntityType, RelationType
from .ner import extract_entities
from .re import extract_relations

__all__ = ["Entity", "Relation", "extract_entities", "extract_relations"]
