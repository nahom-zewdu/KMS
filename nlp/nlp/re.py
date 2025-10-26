# nlp/re.py
# Purpose: Extracts relationships (authored, assigned, fixes) from text and entities using free HuggingFace RE models.

from typing import List, Dict
from transformers import pipeline

# Initialize RE pipeline (free model)
re_pipeline = pipeline("text-classification", model="lihanglei/Multi-RelationExtraction", tokenizer="lihanglei/Multi-RelationExtraction", device=-1)

def extract_relations(text: str, entities: List[Dict]) -> List[Dict]:
    """
    Extracts relationships from text and entities using RE model.
    
    Args:
        text: Input text.
        entities: List of extracted entities.
    
    Returns:
        List of relationships with type and confidence.
    """
    relations = []
    for i in range(len(entities) - 1):
        entity1 = entities[i]["text"]
        entity2 = entities[i+1]["text"]
        input_text = f"{entity1} [REL] {entity2} in {text}"
        result = re_pipeline(input_text)
        if result[0]["score"] > 0.5:
            relations.append({
                "source": entity1,
                "target": entity2,
                "type": result[0]["label"],
                "score": result[0]["score"]
            })
    return relations
