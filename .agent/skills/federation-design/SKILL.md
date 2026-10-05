---
name: federation-design
description: Design cross-domain trust where external execution claims remain attributable, locally evaluated, temporally valid, and independently verifiable.
---

# Federation Design

## Principle

Federation exchanges claims, not implicit trust.

## Inputs

- source trust domain
- relying trust domain
- credentials
- trust bundles
- execution receipts
- local policy

## Outputs

- federation metadata
- trust bundle
- federation credential
- delegation credential
- federated statement
- claim provenance
- revocation model
- local acceptance policy

## Rules

### 1. Local policy wins

A source domain cannot dictate the relying domain's acceptance semantics.

### 2. Provenance is immutable

A claim issued by domain A must remain attributable to A.

### 3. Delegation attenuates

```
effective_policy ⊆ delegated_policy
```

A child cannot expand authority.

### 4. Time matters

Historical trust and current trust are different questions.

### 5. Offline verification

A historical receipt should be verifiable from:
- receipt
- evidence
- attestation
- trust bundle
- local policy

without requiring the source domain to be online.

## Required objects

- TrustDomain
- TrustBundle
- FederationCredential
- DelegationCredential
- FederatedStatement
- TrustExplanation

## Failure modes

Reject:
- unknown trust root
- expired credential
- revoked key
- scope expansion
- provenance laundering
- unsupported assurance translation
- delegation depth overflow

## Acceptance model

```
ACCEPT =
 source evidence valid
 ∧ source domain trusted
 ∧ claim within local policy
 ∧ temporal validity
 ∧ revocation policy satisfied
```
