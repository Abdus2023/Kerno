---
name: skill-creator
description: Create or refactor reusable agent skills from a proven workflow while preserving explicit inputs, outputs, gates, evidence requirements, failure modes, and tool contracts.
---

# Skill Creator

## Purpose

Turn a repeated workflow into a composable skill without losing the reasoning and verification discipline that made the workflow reliable.

## Inputs

- workflow description or prior conversation
- target `.agent` root
- reusable scope
- required tools
- evidence requirements
- failure modes
- output artifacts

## Procedure

1. Extract the workflow as ordered stages.
2. Separate observations, decisions, assumptions, and outputs.
3. Identify deterministic steps versus judgment steps.
4. Convert deterministic steps into tool contracts.
5. Convert judgment steps into explicit gates and decision rules.
6. Define required evidence for every externally verifiable claim.
7. Define failure states and safe stopping conditions.
8. Define reusable inputs and outputs.
9. Add references only when they are stable and actually required.
10. Validate that the skill can run without hidden conversation state.
11. Add negative examples for common failure modes.
12. Register the skill in `.agent/skills/README.md` or an equivalent index.

## Skill contract

Every generated skill must contain:

- frontmatter with `name` and `description`
- Purpose
- Inputs
- Outputs
- Procedure
- Verification gates
- Failure modes
- Evidence policy
- Continuation/state rules

## Quality gate

A skill is not reusable if it depends on phrases such as "continue as before", "use what we found earlier", or undocumented tool state.

Replace hidden state with explicit artifacts:
- snapshot
- evidence ledger
- decision record
- verification report
- continuation state

## Evidence rule

Never turn a search result, code inspection, or model inference into a verified execution claim.

Use:

```
OBSERVED
  !=
DERIVED
  !=
VERIFIED
  !=
EXECUTED
```

## Output

Produce a complete skill directory or SKILL.md plus any referenced schemas/tools.
