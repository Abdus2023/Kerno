"""
Example 17: The runtime tour — cancellation, checkpoints, forking,
replay, and distributed execution, all without an API key.

ScriptedBrain drives the sessions deterministically; the runtime
contracts (audit #83/#59/#58/#104) are exercised end-to-end.
"""

from kerno import (
    AllowList, CancellationToken, CapturePoint, CheckpointStore,
    DistributedExecutor, ScriptedBrain, WorkerPool, fork_session,
    make_executor, replay_session, run,
)
from kerno.kernel.runtime import KernelRuntime


def main() -> None:
    # ── 1. Live session with host-side checkpoints (K-007) ───────────────
    store   = CheckpointStore()
    capture = CapturePoint(store, "tour", every_n=2)

    live = run(
        "Compute values",
        llm=ScriptedBrain(
            "x = 21\nprint('x =', x)",
            "y = x * 2\nprint('y =', y)",
            "# TASK_COMPLETE: done",
        ),
        allowlist=AllowList.data_analysis(),
        max_cells=5,
    )
    print("1. live session:", live.status.name, "| cells:", live.cells_executed)

    # ── 2. Cancellation (audit #83) ──────────────────────────────────────
    token = CancellationToken()
    token.cancel()
    cancelled = run(
        "Never starts",
        llm=ScriptedBrain("x = 1"),
        max_cells=5,
        cancel_token=token,
        load_default_skills=False,
    )
    print("2. pre-cancelled session:", cancelled.status.name)

    # ── 3. Replay without the LLM (audit #58) ────────────────────────────
    with KernelRuntime() as kernel:
        replayed = replay_session(live, kernel, allowlist=AllowList.data_analysis())
    print("3. replay:", replayed.status.name,
          "| cells:", replayed.cells_executed, "| brain not called")

    # ── 4. Fork with a different brain (audit #59) ───────────────────────
    forked = fork_session(
        live,
        ScriptedBrain("z = x * 10\nprint('z =', z)", "# TASK_COMPLETE: done"),
        up_to_cell=2,
        allowlist=AllowList.data_analysis(),
    )
    print("4. fork:", forked.status.name,
          "| continuation:", forked.cells[2].output.stdout.strip())

    # ── 5. Distributed execution (audit #104) ────────────────────────────
    with WorkerPool(lambda: make_executor("subprocess"), n=2) as pool:
        ex = DistributedExecutor(pool)
        results = [
            ex.execute("print({} * 2)".format(i)).stdout.strip()
            for i in range(4)
        ]
    print("5. distributed:", results)


if __name__ == "__main__":
    main()
