"""
Example 13: Program-scale agent architecture.

Shows how ProgramAgent.create / ProgramAgent.load works,
how an agent accumulates knowledge across sessions,
and how to inspect its identity, knowledge, and capabilities.

This is Level 5 of the persistence taxonomy: program-scale
architecture where the agent grows between sessions.
"""

from __future__ import annotations

from kerno.agent import ProgramAgent, AgentIdentity, AgentProfile, SessionContext
from kerno.llm.adapters import make_llm


def main():
    # ── Create a new agent ──────────────────────────────────────────────────
    # (In production, you'd use a real LLM; here we use a mock)
    llm = make_llm("mock")

    agent = ProgramAgent.create(
        name="analyst",
        description="Financial data analyst",
        goals=[
            "Build accurate predictive models",
            "Learn from every session",
            "Propose reusable analysis skills",
        ],
        directory=".kerno/agents/analyst",
        llm=llm,
    )

    print(f"Created agent: {agent.identity().name}")
    print(f"Goals: {agent.identity().goals}")

    # ── Run several tasks ──────────────────────────────────────────────────
    tasks = [
        "Load and explore the sales dataset from sales.csv",
        "Calculate monthly revenue trends",
        "Identify the top 5 customers by total spending",
        "Build a simple churn prediction model",
        "Export the churn model results to CSV",
    ]

    for i, task in enumerate(tasks, 1):
        print(f"\n--- Task {i}: {task} ---")
        try:
            result = agent.run(task)
            print(f"  Status: {result.status.name}")
            print(f"  Cells executed: {result.cells_executed}")
        except Exception as e:
            # In this demo, mock LLM may not produce real results
            print(f"  Error: {e}")

    # ── Inspect accumulated state ──────────────────────────────────────────
    print("\n=== Agent State After 5 Tasks ===")

    # Identity
    identity = agent.identity()
    print(f"Name: {identity.name}")
    print(f"Description: {identity.description}")

    # Profile statistics
    profile = agent._profile
    print(f"Total sessions: {profile.total_sessions}")
    print(f"Total cells: {profile.total_cells}")
    print(f"Success rate: {profile.success_rate:.1%}")

    # Knowledge
    knowledge = agent.what_do_i_know()
    print(f"\nAccumulated knowledge ({len(knowledge)} observations):")
    for obs in knowledge[:10]:
        print(f"  [{obs.kind.name}] {obs.content[:80]} "
              f"(confidence: {obs.confidence:.2f})")

    # Capabilities
    caps = agent.capabilities()
    print(f"\nActive capabilities ({len(caps)} skills):")
    for skill in caps:
        print(f"  {skill.name} (v{skill.version}): {skill.description}")

    # Recall past sessions
    hits = agent.recall("sales")
    print(f"\nVault search for 'sales' ({len(hits)} results):")
    for h in hits[:5]:
        print(f"  {h.get('session_id', '?')}: {h.get('task', '?')[:60]}")

    print("\nDone. Agent state persisted to .kerno/agents/analyst/")


if __name__ == "__main__":
    main()
