# kerno/steps/compress.py
"""
CompressHistoryStep: keep context window manageable.
"""

from __future__ import annotations

from kerno.interfaces import AgentState


class CompressHistoryStep:
    """
    Compress old history into a summary when the window gets full.
    After compression, only recent cells remain in state.history.
    The summary accumulates — it is never lost.
    """

    def __init__(self, llm, threshold: int = 20, keep_recent: int = 10):
        from kerno.context.compressor import HistoryCompressor
        self.compressor   = HistoryCompressor(llm)
        self.threshold    = threshold
        self.keep_recent  = keep_recent

    def run(self, state: AgentState) -> AgentState:
        if not self.compressor.should_compress(state.history, self.threshold):
            return state

        older       = state.history[:-self.keep_recent]
        new_summary = self.compressor.compress(older)

        state.summary = (
            "{}\n\n{}".format(state.summary, new_summary).strip()
            if state.summary else new_summary
        )
        state.history = state.history[-self.keep_recent:]
        return state


class CompletionCheckStep:
    """
    Check if the TASK_COMPLETE signal has been emitted.
    Sets state.complete = True if so.
    """

    SIGNAL = "# TASK_COMPLETE"

    def run(self, state: AgentState) -> AgentState:
        last_code = state.metadata.get("last_code", "")
        if self.SIGNAL in last_code:
            state.complete = True
        return state
