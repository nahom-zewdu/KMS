import pandas as pd
import re
import uuid

# Load the provided CSV data
data = pd.read_csv("data/raw_data.csv")

# Define entities for annotation
projects = ["payment API", "user service", "auth module", "billing system", "order service", "DB schema", "frontend UI", "search API", "notification service", "analytics dashboard", "security gateway", "checkout flow"]
names = [r"\[NAME\d+\]"]  # Regex for [NAME1], [NAME2], etc.
tickets = [r"JIRA-\d+", r"PR #\d+", r"ISSUE-\d+"]  # Regex for tickets

# Annotation function
def annotate_content(content):
    entities = []
    # PERSON: [NAME\d+]
    for match in re.finditer(r'\[NAME\d+\]', content):
        entities.append((match.start(), match.end(), "PERSON"))
    # PROJECT: exact match from projects list
    for proj in projects:
        for match in re.finditer(re.escape(proj), content):
            entities.append((match.start(), match.end(), "PROJECT"))
    # TICKET: JIRA-\d+, PR #\d+, ISSUE-\d+
    for ticket_pattern in tickets:
        for match in re.finditer(ticket_pattern, content):
            entities.append((match.start(), match.end(), "TICKET"))
    # Sort by start position and resolve overlaps
    entities = sorted(entities, key=lambda x: x[0])
    non_overlapping = []
    last_end = -1
    for start, end, label in entities:
        if start >= last_end:
            non_overlapping.append((start, end, label))
            last_end = end
    return non_overlapping

# Add entities column
data['entities'] = data['content'].apply(annotate_content)

# Save annotated data to CSV
data.to_csv("data/annotated_data.csv", index=False)

# Output JSON for preview
print(data.head(20).to_json(orient='records', lines=True))