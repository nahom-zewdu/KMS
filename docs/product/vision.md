# Product Vision

> Status: working hypothesis. This is a product thesis to validate, not a statement that customers have already confirmed.

## Problem

Engineering knowledge is distributed across conversations, code, pull requests, people, and undocumented decisions. A new engineer can often find files and documentation yet still struggle to determine what matters, who owns it, how systems fit together, and why things are the way they are.

The expensive problem is therefore **context acquisition**, not simply missing documentation.

## KMS thesis

KMS should turn the organization's accumulated engineering activity into useful, company-specific context that helps engineers become effective faster and recover context without repeatedly interrupting other engineers.

The current product wedge is **First 7 Days / Ramp**: generate a role-specific onboarding path grounded in the customer's actual codebase, ownership signals, architecture, and engineering knowledge.

## Differentiation hypothesis

A generic AI onboarding checklist is not enough. KMS must produce recommendations that are traceable to evidence from the customer's environment and improve as KMS accumulates context.

The intended loop is:

```text
Connect engineering systems
        ↓
Capture company-specific signals
        ↓
Build useful context
        ↓
Generate grounded guidance
        ↓
Engineer uses it
        ↓
Measure whether context acquisition improved
        ↓
Learn and improve
```

## First customer hypothesis

The initial target is an engineering organization where onboarding and context transfer are materially expensive, particularly teams with multiple services/repos and meaningful dependence on experienced engineers.

This is a hypothesis. Buyer, team size, willingness to pay, and the strongest use case must be validated through real customer conversations and usage.

## Product discipline

KMS is not trying to become a general-purpose engineering platform during MVP validation. We should build the smallest end-to-end workflow that proves a customer outcome, then expand from demonstrated demand.

## Success condition

The product earns continued use because an engineer can reach useful independence or recover important engineering context faster and with less human interruption than the team's existing process.
