"""Security invariant suite — the release gate (P3.16).

Compact, kernel-free invariant tests that must hold on every release.
Each test asserts one security invariant end-to-end (choke point, origin
authority, capability/allowlist pre-execution denial, profile governance,
SSRF policy, materialization bounds, isolation, streaming parity,
finalization).
"""
