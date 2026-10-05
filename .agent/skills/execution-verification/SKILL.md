---
name: execution-verification
description: Verify execution claims only from execution evidence bound to the exact repository artifact and required execution kind.
---

# Execution Verification

This skill evaluates claims about things that actually ran.

Example:

`tests passed`

requires evidence from an execution authority, not merely test files or CI configuration.

## Matching rule

Evidence must match all of:

- claim evidence ID
- repository
- exact commit
- exact tree
- required execution kind

## Decisions

- PASS: matching authority reports PASSED.
- FAIL: matching execution reports failure, cancellation, or timeout.
- INDETERMINATE: matching execution exists but success is not observable.
- BLOCKED: no matching execution evidence exists.

## Prohibition

Never convert static evidence into execution evidence.
Never substitute a branch, tag, or workflow definition for the exact artifact identity.
