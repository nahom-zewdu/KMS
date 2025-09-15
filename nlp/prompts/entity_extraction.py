from langchain.prompts import PromptTemplate

entity_extraction_prompt = PromptTemplate(
    input_variables=["text"],
    template="""Extract entities (PERSON: names like Nahom, PROJECT: APIs/services like github, payment API, TICKET: formats like JIRA-123, Jira #123, PR #123) from: '{text}'.
Output JSON: {"entities": [{"type": "person/project/ticket", "name": "extracted", "start": 0, "end": 5}]}
Example: Input: "Nahom owns github, Jira #435" -> {"entities": [{"type": "person", "name": "Nahom", "start": 0, "end": 5}, {"type": "project", "name": "github", "start": 11, "end": 17}, {"type": "ticket", "name": "Jira #435", "start": 19, "end": 28}]}
Do not hallucinate or add entities not present in the text."""
)