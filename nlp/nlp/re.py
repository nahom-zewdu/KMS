# nlp/re.py
# Purpose: Extracts relationships (authored, assigned, fixes) from text and entities using a free HuggingFace text-classification model.

from typing import List, Dict
from transformers import pipeline

# Initialize text-classification pipeline (using a public model)
re_pipeline = pipeline("text-classification", model="bert-base-uncased", tokenizer="bert-base-uncased", device=-1)

def extract_relations(text: str, entities: List[Dict]) -> List[Dict]:
    """
    Extracts relationships from text and entities using a text-classification model.
    
    Args:
        text: Input text.
        entities: List of extracted entities.
    
    Returns:
        List of relationships with type and confidence.
    """
    relations = []
    relation_types = ["authored", "assigned", "fixes"]  # Define possible relation types
    for i in range(len(entities) - 1):
        entity1 = entities[i]["text"]
        entity2 = entities[i+1]["text"]
        for rel_type in relation_types:
            input_text = f"Does {entity1} {rel_type} {entity2} in the context: {text}?"
            result = re_pipeline(input_text)
            # Assume positive label (e.g., LABEL_1) indicates a valid relation
            if result[0]["label"] == "LABEL_1" and result[0]["score"] > 0.5:
                relations.append({
                    "source": entity1,
                    "target": entity2,
                    "type": rel_type,
                    "score": result[0]["score"]
                })
    return relations
