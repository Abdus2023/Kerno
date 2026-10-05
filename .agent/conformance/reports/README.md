# Conformance execution reports

This directory contains generated reports from actual harness executions.

Reports are execution evidence only when their invocation and environment can be independently
established. A report committed to Git is not, by itself, CI evidence.

The expected core report is:

`.agent/conformance/reports/core-reference-latest.json`

The runner covers the deterministic reference-resolution, expression-evaluation, and state-machine
fixtures. Authorization, temporal, evidence, interchange, and governance remain separate domains
until their semantic adapters are implemented.
