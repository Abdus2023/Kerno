---
name: protocol-freeze
description: Convert a trust architecture into an interoperable protocol with canonical schemas, cryptographic domains, versioning, conformance vectors, and deterministic verification.
---

# Protocol Freeze

## Purpose

Make two independent implementations interoperable without shared implementation code.

## Inputs

- runtime/receipt design
- federation design
- cryptographic requirements
- API requirements
- conformance requirements

## Outputs

- versioned schemas
- canonical serialization rules
- crypto profile
- signature domains
- digest rules
- stable errors
- API contract
- conformance vectors
- security considerations

## Normative rules

Freeze:
- schema identifiers
- major-version compatibility
- canonical serialization
- digest format
- signature encoding
- signature domains
- timestamp semantics
- error codes
- extension rules

## Canonicalization

Cryptographically committed objects must have exactly one canonical byte representation.

Reject:
- duplicate keys
- ambiguous numbers
- unsupported non-finite values
- implementation-dependent serialization

## Domain-separated signatures

Every signed object gets a unique signature domain.

Do not reuse a signing domain for semantically unrelated objects.

## Verification reproducibility

Record:
- receipt digest
- verification policy digest
- trust bundle digest
- verifier artifact/version
- verification time

Same inputs and same verifier semantics should yield the same decision.

## Conformance

Require:
- positive vectors
- negative vectors
- cross-language vectors
- malformed input tests
- replay tests
- expiry tests
- delegation attenuation tests
- canonicalization tests

## Definition of done

A second implementation can:
1. parse the schemas
2. reproduce canonical bytes
3. verify signatures
4. reconstruct evidence roots
5. verify receipts
6. reject the same adversarial vectors
