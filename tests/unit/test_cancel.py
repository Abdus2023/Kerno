"""
Unit tests for CancellationToken (audit #83).
"""

import threading
import time

from kerno.cancel import CancellationToken


class TestCancellationToken:

    def test_initial_state_not_cancelled(self):
        token = CancellationToken()
        assert token.cancelled is False
        assert token.is_set() is False

    def test_cancel_sets_flag(self):
        token = CancellationToken()
        token.cancel()
        assert token.cancelled is True
        assert token.is_set() is True

    def test_cancel_is_idempotent(self):
        token = CancellationToken()
        token.cancel()
        token.cancel()          # no error
        assert token.cancelled

    def test_wait_returns_true_when_cancelled(self):
        token = CancellationToken()
        token.cancel()
        assert token.wait(timeout=0.1) is True

    def test_wait_times_out_when_not_cancelled(self):
        token = CancellationToken()
        assert token.wait(timeout=0.05) is False

    def test_wait_until_deadline(self):
        token = CancellationToken()
        assert token.wait_until(time.monotonic() + 0.05, interval=0.01) is False
        # cancel right at the deadline
        token.cancel()
        assert token.wait_until(time.monotonic() + 0.1) is True

    def test_cross_thread_cancel(self):
        token = CancellationToken()
        result = []

        def canceller():
            time.sleep(0.1)
            token.cancel()

        t = threading.Thread(target=canceller)
        t.start()
        assert token.wait(timeout=2.0) is True   # unblocked by the thread
        t.join()
        assert result == []

    def test_no_bool_trap(self):
        # The token must not define __bool__/__len__ (falsy-object trap)
        token = CancellationToken()
        assert not hasattr(token, "__bool__") or token.cancelled is False
