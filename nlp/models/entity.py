from dataclasses import dataclass
from typing import List

@dataclass
class Entity:
    type: str
    name: str
    start: int
    end: int

@dataclass
class Relationship:
    source_name: str
    target_name: str
    type: str
    metadata: dict