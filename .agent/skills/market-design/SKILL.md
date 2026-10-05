---
name: market-design
description: Build an execution market above verified runtime infrastructure where capability, assurance, execution, usage, settlement, and reputation remain separate and evidence-backed.
---

# Execution Market Design

## Principle

Money can reward verified execution. Money cannot manufacture verification.

## Inputs

- execution intent
- provider advertisements
- assurance requirements
- pricing
- selection policy
- receipts
- usage evidence
- settlement terms

## Outputs

- intent
- provider advertisement
- quote
- selection
- usage record
- settlement receipt
- dispute record
- reputation record

## Market lifecycle

```
intent
 -> eligibility
 -> quote
 -> selection
 -> lease
 -> execution
 -> evidence
 -> verification
 -> settlement
```

## Matching

Filter by:
- assurance
- capabilities
- policy compatibility
- time
- domain restrictions
- settlement compatibility

Only then optimize price/latency.

## Assurance rule

An advertised assurance level is a capability claim, not proof.

A completed execution must independently satisfy the assurance requirements.

## Settlement rule

```
SettlementValid =
 quote_valid
 ∧ selection_valid
 ∧ lease_valid
 ∧ receipt_valid
 ∧ verification_accepts
 ∧ usage_valid
 ∧ terms_satisfied
```

## Reputation

Reputation must derive from verified history, not provider self-reporting.

Scope reputation by:
- task class
- assurance
- runtime class
- capability set
- time window

## Threats

Test:
- assurance downgrade
- quote mutation
- usage inflation
- Sybil reputation
- fake capacity
- selective execution
- settlement before verification
- dispute manipulation
