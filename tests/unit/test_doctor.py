"""
Unit tests for `kerno doctor` — the environment + runtime invariant
diagnostic (operational K-010 tooling).
"""

from kerno.cli.main import check_runtime_invariants


class TestDoctorRuntimeInvariants:

    def test_invariants_check_passes_on_healthy_runtime(self):
        ok, detail = check_runtime_invariants()
        assert ok is True
        assert "P1-P10" in detail

    def test_invariants_check_detects_broken_p5(self):
        # Patch check_monotonic_sequence to fail → the doctor reports it
        import kerno.invariants as inv
        from types import SimpleNamespace as NS

        original = inv.check_monotonic_sequence
        def broken(events):
            raise inv.InvariantViolation("P5 violated: injected")
        inv.check_monotonic_sequence = broken
        try:
            ok, detail = check_runtime_invariants()
            assert ok is False
            assert "P5" in detail
        finally:
            inv.check_monotonic_sequence = original
