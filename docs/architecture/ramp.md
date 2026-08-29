# Ramp Architecture

## Purpose

Ramp is the current customer-facing wedge for KMS. It uses company-specific codebase and knowledge signals to construct a role-specific First 7 Days onboarding path.

## Current generation model

`RampPlanGenerator` builds a deterministic plan from VisualizerService output plus ownership signals from `codebase_files.last_author` and `OWNS` graph edges. It can use an LLM to polish the explanatory `why` text, while the structural facts are intended to remain grounded.

Plans are company- and role-scoped and persisted in `ramp_plans`.

## Step model

The generator produces up to seven steps containing structured fields such as ordering, title, rationale, risk tier, owners, target, summary, resources, checklist, evidence, machine-readable data, and overrides. Step identity is designed to be stable for deep-linking/workspace use.

## Product constraint

Ramp should not become a generic onboarding checklist generator. Its differentiator must come from evidence specific to the customer's codebase, ownership, architecture, and accumulated engineering context.

## Open validation questions

- Do engineers trust the generated path enough to follow it?
- Does it reduce time-to-context versus existing onboarding?
- Which evidence types produce the most useful recommendations?
- Who experiences the pain strongly enough to buy it?
