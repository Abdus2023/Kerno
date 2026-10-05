---
name: gpjk-authorization
description: Separate capability, authority, policy, and verification when deciding whether a governed process action is permitted.
---

# GPJK Authorization

## Purpose
Evaluate permission independently from occurrence and later verification.

## Inputs
- actor
- action
- resource
- process/version
- execution
- context
- policy/version
- delegation/capability evidence

## Outputs
- permit, deny, or indeterminate
- authorization trace
- obligations/prohibitions

## Procedure
1. Bind the exact policy version.
2. Identify actor, action, resource, and process/version.
3. Evaluate delegation and capability separately.
4. Apply policy rules.
5. Default unknown authorization to deny unless an explicit policy says otherwise.
6. Record obligations and prohibitions.
7. Preserve unauthorized occurrences as facts plus judgment.
8. Keep authorization separate from verification.

## Gates
A1 identity; A2 policy binding; A3 resource/action binding; A4 decision; A5 trace.

## Failure modes
Policy substitution, capability treated as authority, unknown treated as permit, missing resource binding, authorization result used as proof of execution.

## Evidence policy
Authorization proves a policy decision within its scope, not that an authorized action actually occurred.
