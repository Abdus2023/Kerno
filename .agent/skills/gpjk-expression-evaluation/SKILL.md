---
name: gpjk-expression-evaluation
description: Evaluate declarative GPJK expressions with explicit types and three-valued TRUE/FALSE/UNKNOWN semantics.
---

# GPJK Expression Evaluation

## Purpose
Evaluate process conditions and verification assertions without implicit coercion or arbitrary host execution.

## Inputs
- expression
- reference-resolution context
- function registry

## Outputs
- TRUE, FALSE, or UNKNOWN
- evaluation trace
- invalid-expression diagnostic when syntax/typing is invalid

## Procedure
1. Parse the expression.
2. Validate grammar.
3. Resolve references.
4. Apply strict type rules.
5. Evaluate comparison, logical, and permitted pure functions.
6. Propagate UNKNOWN according to the defined three-valued tables.
7. Distinguish invalid expressions from UNKNOWN.
8. Emit a trace of resolved operands and results.

## Gates
X1 grammar; X2 type validity; X3 reference resolution; X4 three-valued semantics; X5 purity.

## Failure modes
Implicit coercion, arbitrary code execution, invalid expression classified as UNKNOWN, unresolved reference silently defaulted, non-deterministic function.

## Evidence policy
An evaluation trace proves what the evaluator computed from its inputs; it does not prove that the inputs themselves are true.
