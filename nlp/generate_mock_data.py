import pandas as pd
import uuid
import random

# Lists for generating realistic data
projects = ["payment API", "user service", "auth module", "billing system", "order service", "DB schema", "frontend UI", "search API", "notification service", "analytics dashboard", "security gateway", "checkout flow"]
tickets = [f"JIRA-{random.randint(100, 999)}" for _ in range(100)] + [f"PR #{random.randint(100, 999)}" for _ in range(100)] + [f"ISSUE-{random.randint(100, 999)}" for _ in range(50)]
names = ["[NAME1]", "[NAME2]", "[NAME3]", "[NAME4]", "[NAME5]"]
emojis = ["😂","🙄","🤨","😡","🤬","💀","💩","🐱‍👤","🐐","🧠","👆","💪","🤏","🖐","👏","🙏","🤝","❤","🧡","🚀", "😅", "🔥", "✅", "⚠️", "🛠️", "📈", "❗",]
code_snippets = ["<code>SELECT * FROM users WHERE id = 1;</code>", "<code>app.get('/api/payment')</code>", "<code>try { ... } catch (e) { console.log(e); }</code>", "<code>def process_payment(): ...</code>", ""]
urls = ["https://jira.acme.com/browse/JIRA-123", "https://github.com/acme/repo/pull/789", "https://docs.acme.com/payment-api", "https://slack.com/archives/C12345678/p1234567890", ""]

# Expanded Slack templates (15 formats, mimicking threads)
slack_templates = [
    "{name} mentioned: Hey team, {project} is down again {emoji}. Checking logs now.",
    "Quick update in thread: {name} fixed {project} via {ticket}. Here's the link: {url}",
    "@team {project} deployment failed {emoji}. Do we need a rollback? Thoughts?",
    "{name}: Just pushed changes to {project}. Can someone review {ticket} please?",
    "Bug report: {project} causing crash with this error {code}. {name} investigating.",
    "Discussion thread: Why did we redesign {project}? Context in {ticket}.",
    "{name} shared a doc: {url} for troubleshooting {project} issues.",
    "Onboarding note: {project} is owned by {name}. Ping them for questions.",
    "Prod alert ⚠️: {project} latency spiking {emoji} – Let's investigate {ticket}.",
    "{name} replied in thread: Fixed the issue in {project}, merged to main branch.",
    "Question for the team: Who handles auth for {project}? Is it {name}?",
    "Success! {project} v2 is live {emoji} – great work {name}! Release notes: {url}",
    "{name}: Here's a quick {code} snippet for the {project} fix. What do you think?",
    "Thread starter: Planning refactor for {project}. Input from {name} and others?",
    "Error log from {project}: Threw exception {code} during {ticket} implementation."
]

# Expanded Jira templates (15 formats, mimicking tickets)
jira_templates = [
    "{ticket} - Summary: Critical bug in {project}. Description: {name} reported intermittent crashes in production environment.",
    "{ticket} - Assignee: {name}, Priority: High, Labels: bug, {project}, urgent",
    "{ticket} - Type: Task, Component: {project}, Due Date: 2025-08-20, Status: To Do",
    "{ticket} - Description: Optimize {project} for better scalability and performance. Reference docs: {url}",
    "{ticket} - Epic Link: {project} redesign, Child Stories: Implement new auth flow.",
    "{ticket} - Comment by {name}: Attached debug logs {code}. Reproducible in staging.",
    "{ticket} - Status: In Progress, Resolution: Pending, Affected Versions: v1.2.3",
    "{ticket} - Created by {name}, Affects: {project}, Fix Version: v2.0",
    "{ticket} - Linked Issues: Blocks {ticket}, Relates to {project} migration task",
    "{ticket} - Acceptance Criteria: {project} must handle 1000 QPS with <100ms latency.",
    "{ticket} - Environment: Production, Steps to Reproduce: 1. Call {project} endpoint, 2. Observe error.",
    "{ticket} - Attachments: Screenshot of {project} dashboard error, Log file.",
    "{ticket} - Sprint: Q3 2025, Story Points: 5, Assignee: {name}",
    "{ticket} - Watchers: {name}, Voters: 3, Priority: Blocker",
    "{ticket} - Resolution: Fixed, Verified by {name} in QA environment. Close ticket."
]

# Expanded GitHub templates (15 formats, mimicking PRs/commits)
github_templates = [
    "{ticket}: Refactor {project} for better modularity. Description: Updated code structure and added unit tests.",
    "Commit by {name}: Fix minor bug in {project} {code}. Addresses edge case.",
    "Pull Request {ticket} from {name}: Add new feature to {project}. Changes: {code}, see diff for details.",
    "Merged {ticket}: {project} updates approved by reviewers. No conflicts.",
    "Issue {ticket}: {project} not handling invalid inputs correctly in prod.",
    "Comment on {ticket}: {name} suggested alternative {code} implementation for efficiency.",
    "Branch: feature/{project}, Commit: Initial setup with dependencies installed.",
    "{ticket} closed by {name}: Resolved with commit hash abc123. Verification: {url}",
    "Pull Request {ticket}: Title: Update deps for {project}, Body: Security patches applied.",
    "Commit message: Bump {project} version to 2.0 – includes breaking changes.",
    "{ticket} labeled: bug, enhancement, {project}",
    "Milestone: v3 Release, Assignees: {name}, Reviewers: {project} team",
    "Diff in {ticket}: - Old code line\n+ New code line for {project} fix",
    "Review comment on {ticket}: {name} approved changes to {project} with minor suggestions.",
    "{ticket} reopened: {project} issue persists after merge. Needs further investigation."
]

# Generate 1000 samples
data = []
for i in range(600):  # Slack: 600
    id_val = str(uuid.uuid4())
    template = random.choice(slack_templates)
    content = template.format(
        name=random.choice(names),
        project=random.choice(projects),
        ticket=random.choice(tickets),
        emoji=random.choice(emojis),
        code=random.choice(code_snippets),
        url=random.choice(urls)
    )
    data.append({"id": id_val, "content": content, "source": "slack"})

for i in range(200):  # Jira: 200
    id_val = str(uuid.uuid4())
    template = random.choice(jira_templates)
    content = template.format(
        name=random.choice(names),
        project=random.choice(projects),
        ticket=random.choice(tickets),
        code=random.choice(code_snippets),
        url=random.choice(urls)
    )
    data.append({"id": id_val, "content": content, "source": "jira"})

for i in range(200):  # GitHub: 200
    id_val = str(uuid.uuid4())
    template = random.choice(github_templates)
    content = template.format(
        name=random.choice(names),
        project=random.choice(projects),
        ticket=random.choice(tickets),
        code=random.choice(code_snippets),
        url=random.choice(urls)
    )
    data.append({"id": id_val, "content": content, "source": "github"})

# Save to CSV
df = pd.DataFrame(data)
df.to_csv("data/raw_data.csv", index=False)
print("Generated 1000 samples. Preview:")
print(df.head(20))