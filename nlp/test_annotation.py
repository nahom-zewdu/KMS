import pandas as pd
import re
import ast

# Define expected patterns for validation
projects = [
    "payment API", "user service", "auth module", "billing system", "order service",
    "DB schema", "frontend UI", "search API", "notification service",
    "analytics dashboard", "security gateway", "checkout flow"
]
name_pattern = r"^\[NAME\d+\]$"  # e.g., [NAME1]
ticket_patterns = [
    r"^JIRA-\d+$",  # e.g., JIRA-123
    r"^PR #\d+$",   # e.g., PR #458
    r"^ISSUE-\d+$"  # e.g., ISSUE-894
]

def validate_entity(content, start, end, label):
    """Validate a single entity's correctness."""
    # Extract substring
    try:
        entity_text = content[start:end]
    except IndexError:
        return False, f"Invalid indices: start={start}, end={end} for content length={len(content)}"
    
    # Check if substring matches expected pattern for the label
    if label == "PERSON":
        if not re.match(name_pattern, entity_text):
            return False, f"PERSON entity '{entity_text}' does not match pattern {name_pattern}"
    elif label == "PROJECT":
        if entity_text not in projects:
            return False, f"PROJECT entity '{entity_text}' not in known projects: {', '.join(projects)}"
    elif label == "TICKET":
        if not any(re.match(pattern, entity_text) for pattern in ticket_patterns):
            return False, f"TICKET entity '{entity_text}' does not match any pattern: {', '.join(ticket_patterns)}"
    else:
        return False, f"Unknown label: {label}"
    
    return True, f"Valid: '{entity_text}' ({label})"

def test_annotations(csv_file):
    """Test the correctness of annotations in the CSV file."""
    # Load annotated data
    try:
        data = pd.read_csv(csv_file)
    except FileNotFoundError:
        print(f"Error: {csv_file} not found.")
        return
    
    # Initialize counters
    total_entities = 0
    invalid_entities = 0
    
    # Iterate through rows
    for index, row in data.iterrows():
        content = row['content']
        # Parse entities (stored as string representation of list)
        try:
            entities = ast.literal_eval(row['entities'])
        except (ValueError, SyntaxError):
            print(f"Row {index} (ID: {row['id']}): Invalid entities format: {row['entities']}")
            invalid_entities += 1
            continue
        
        # print(f"\nRow {index} (ID: {row['id']}):")
        # print(f"Content: {content}")
        # print("Entities:")
        
        for start, end, label in entities:
            total_entities += 1
            is_valid, message = validate_entity(content, start, end, label)
            if not is_valid:
                print(f"  - {message}")
                invalid_entities += 1
        
        # Check for overlapping entities
        last_end = -1
        for start, end, label in sorted(entities, key=lambda x: x[0]):
            if start < last_end:
                print(f"  - Warning: Overlapping entities detected at start={start}, end={end}")
                invalid_entities += 1
            last_end = max(last_end, end)
    
    # Summary
    print(f"\nValidation Summary:")
    print(f"Total entities checked: {total_entities}")
    print(f"Invalid entities: {invalid_entities}")
    print(f"Accuracy: {(total_entities - invalid_entities) / total_entities * 100:.2f}%")

if __name__ == "__main__":
    test_annotations("annotated_data.csv")