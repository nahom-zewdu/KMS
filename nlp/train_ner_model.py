import pandas as pd
import spacy
from spacy.training import Example
import random
from sklearn.model_selection import train_test_split
import ast

# Load annotated data
def load_data(csv_file):
    try:
        data = pd.read_csv(csv_file)
    except FileNotFoundError:
        print(f"Error: {csv_file} not found.")
        return []
    
    training_data = []
    for _, row in data.iterrows():
        text = row['content']
        try:
            entities = ast.literal_eval(row['entities'])
        except (ValueError, SyntaxError):
            print(f"Skipping row ID {row['id']}: Invalid entities format.")
            continue
        training_data.append((text, {"entities": entities}))
    return training_data

# Convert to spaCy format and split data
def prepare_training_data(csv_file):
    data = load_data(csv_file)
    train_data, valid_data = train_test_split(data, test_size=0.2, random_state=42)
    return train_data, valid_data

# Train spaCy NER model
def train_ner_model(train_data, valid_data, output_dir="ner_model", n_iter=80):
    # Load a blank English model (use the latest spaCy v3.x; ensure you have spacy >= 3.0 installed)
    nlp = spacy.load("en_core_web_sm")
    if "ner" not in nlp.pipe_names:
        ner = nlp.add_pipe("ner")
    else:
        ner = nlp.get_pipe("ner")
    
    # Add labels
    for _, annotations in train_data:
        for ent in annotations["entities"]:
            ner.add_label(ent[2])
    
    # Disable other pipelines
    other_pipes = [pipe for pipe in nlp.pipe_names if pipe != "ner"]
    with nlp.disable_pipes(*other_pipes):
        optimizer = nlp.begin_training()
        for itn in range(n_iter):
            random.shuffle(train_data)
            losses = {}
            for text, annotations in train_data:
                doc = nlp.make_doc(text)
                example = Example.from_dict(doc, annotations)
                nlp.update([example], drop=0.5, sgd=optimizer, losses=losses)
            print(f"Iteration {itn + 1}, Losses: {losses}")
    
    # Evaluate on validation data
    if valid_data:
        print("\nEvaluating on validation data...")
        correct = 0
        total = 0
        for text, annotations in valid_data:
            doc = nlp(text)
            predicted = [(ent.start_char, ent.end_char, ent.label_) for ent in doc.ents]
            expected = annotations["entities"]
            correct += sum(1 for ent in predicted if ent in expected)
            total += len(expected)
        accuracy = (correct / total * 100) if total > 0 else 0
        print(f"Validation Accuracy: {accuracy:.2f}%")
    
    # Save model
    nlp.to_disk(output_dir)
    print(f"Model saved to {output_dir}")

# Test the model on a sample
def test_model(model_dir, text):
    nlp = spacy.load(model_dir)
    doc = nlp(text)
    print("\nTest Example:")
    print(f"Text: {text}")
    print("Entities:")
    for ent in doc.ents:
        print(f"  - {ent.text} ({ent.label_})")

if __name__ == "__main__":
    # Load and prepare data
    train_data, valid_data = prepare_training_data("data/annotated_data.csv")
    print(f"Training samples: {len(train_data)}, Validation samples: {len(valid_data)}")
    
    # Train model
    train_ner_model(train_data, valid_data, output_dir="ner_model")
    
    # Test on a sample
    sample_text = "Success! payment API v2 is live - great work [NAME3]! Let's investigate JIRA-123."
    test_model("ner_model", sample_text)