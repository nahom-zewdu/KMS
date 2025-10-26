# nlp/ner.py
# Purpose: Extracts entities (PERSON, PROJECT, TICKET) from text using free HuggingFace NER models.

from typing import List, Dict
from transformers import pipeline

# Initialize NER pipeline (free model)
ner_pipeline = pipeline("ner", model="dslim/bert-base-NER", tokenizer="dslim/bert-base-NER", device=-1)

def extract_entities(text: str) -> List[Dict]:
    """
    Extracts entities from text using NER model.
    
    Args:
        text: Input text (e.g., Slack message or GitHub PR body).
    
    Returns:
        List of extracted entities with label and confidence.
    """
    results = ner_pipeline(text)
    entities = []
    for r in results:
        if r["score"] > 0.5:
            entities.append({
                "text": r["word"],
                "label": r["entity"],
                "score": r["score"]
            })
    return entities
