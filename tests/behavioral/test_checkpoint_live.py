"""
Behavioral: live sessions record host-side checkpoints (K-007) — bound
to the engine's event sequence and the kernel generation, with lineage.
"""

import pytest

from kerno.core.capture import CapturePoint
from kerno.core.checkpoint import CheckpointStore
from kerno.execution.engine import ExecutionEngine
from kerno.kernel.runtime import KernelRuntime
from kerno.loop.reactive import ReactiveLoop
from kerno.types import Message, SessionStatus


def make_llm(*responses):
    responses = list(responses)
    state = {"i": 0}

    def llm(messages: list[Message]) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(responses):
            return responses[i]
        return "# TASK_COMPLETE: done"

    return llm


@pytest.mark.integration
class TestLiveCheckpoints:

    def test_session_records_checkpoints_with_event_sequence(self, tmp_path):
        kernel = KernelRuntime()
        kernel.start()
        try:
            engine  = ExecutionEngine(kernel)
            store   = CheckpointStore(persist_dir=str(tmp_path / "ckpts"))
            capture = CapturePoint(store, "sess-live", engine=engine, kernel=kernel)

            loop = ReactiveLoop(
                kernel=engine, llm=make_llm(
                    "x = 21\nprint('x =', x)",
                    "y = x * 2\nprint('y =', y)",
                    "# TASK_COMPLETE: done",
                ),
                max_cells=10,
            )
            result = loop.run("checkpointed session", capture=capture)

            assert result.status == SessionStatus.COMPLETE
            # One checkpoint per successful cell (3 cells → 3 checkpoints)
            assert capture.count == 3
            ckpts = store.latest("sess-live")
            assert ckpts is not None
            # K-007: bound to the engine's event position + generation
            assert ckpts.event_sequence == engine.event_sequence
            assert ckpts.kernel_generation == 1
            # Lineage chain: each checkpoint parents the next
            all_ck = [c for c in store._checkpoints.values()]
            assert len(all_ck) == 3
            assert all_ck[1].parent_checkpoint_id == all_ck[0].checkpoint_id
            assert all_ck[2].parent_checkpoint_id == all_ck[1].checkpoint_id

            # The checkpoints persisted to disk
            assert len(list((tmp_path / "ckpts").glob("ckpt_*.json"))) == 3
        finally:
            kernel.shutdown()

    def test_fork_from_live_checkpoint(self, tmp_path):
        """Audit #59: fork an experiment from a mid-session checkpoint."""
        kernel = KernelRuntime()
        kernel.start()
        try:
            engine  = ExecutionEngine(kernel)
            store   = CheckpointStore()
            capture = CapturePoint(store, "sess-fork", engine=engine, kernel=kernel)

            loop = ReactiveLoop(
                kernel=engine, llm=make_llm(
                    "x = 21\nprint('x =', x)",
                    "print('continue A')",
                    "# TASK_COMPLETE: done",
                ),
                max_cells=10,
            )
            loop.run("forkable session", capture=capture)

            mid = store._checkpoints[
                [c for c in store._checkpoints
                 if "cell 2" in store._checkpoints[c].summary][0]
            ]
            forked = store.fork(mid.checkpoint_id)
            assert forked.parent_checkpoint_id == mid.checkpoint_id
            assert forked.state_version == mid.state_version
            assert forked.event_sequence == mid.event_sequence
        finally:
            kernel.shutdown()
