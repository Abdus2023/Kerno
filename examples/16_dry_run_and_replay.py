"""
Example 16: Dry-run mode and replay without the LLM.

  - run(mode="dry_run") validates the whole session — policy applied,
    cells produced — without EVER starting a kernel (audit #91).
  - replay_session() re-executes a recorded session with NO LLM
    (audit #58), so debugging and CI never depend on a live model.

Runs WITHOUT an API key: ScriptedBrain is a deterministic LLM.
"""

from kerno import (
    AllowList, ScriptedBrain, replay_session, run,
    save_session, load_session,
)


def main() -> None:
    # ── 1. Dry run: no kernel started ────────────────────────────────────
    dry = run(
        "Compute values",
        llm=ScriptedBrain(
            "x = 21\nprint('x =', x)",
            "# TASK_COMPLETE: done",
        ),
        allowlist = AllowList.data_analysis(),
        mode      = "dry_run",
        max_cells = 5,
    )
    print("dry-run status:", dry.status.name)
    print("dry-run cell 1 stdout:", dry.cells[0].output.stdout[:60])

    # ── 2. Live run (real kernel) ────────────────────────────────────────
    live = run(
        "Compute values",
        llm=ScriptedBrain(
            "x = 21\nprint('x =', x)",
            "y = x * 2\nprint('y =', y)",
            "# TASK_COMPLETE: done",
        ),
        allowlist = AllowList.data_analysis(),
        max_cells = 5,
    )
    print("live status:", live.status.name, "| cells:", live.cells_executed)

    # ── 3. Replay the live session with NO LLM ───────────────────────────
    from kerno.kernel.runtime import KernelRuntime
    with KernelRuntime() as kernel:
        replayed = replay_session(live, kernel, allowlist=AllowList.data_analysis())
    print("replay status:", replayed.status.name,
          "| cells:", replayed.cells_executed)

    # ── 4. Sessions persist as JSON for later resume / audit ─────────────
    path = save_session(live, "_kerno/example16_session.json")
    loaded = load_session(path)
    print("saved session:", path, "| loaded cells:", loaded.cells_executed)

    # Deterministic cells reproduce identical output on replay
    assert replayed.cells[0].output.stdout == live.cells[0].output.stdout
    print("\n✅ dry-run, live, replay, and persistence all consistent")


if __name__ == "__main__":
    main()
