# Workflow state machine

```
DISCOVER → FREEZE → MODEL → IMPLEMENT → TEST → VERIFY → RELEASE_GATE → TAG
```

Terminal states:

- RELEASED
- BLOCKED

A blocked state is recoverable only after new evidence changes the blocking condition.

## Invariants

1. Every state transition has an actor/tool.
2. Every verification transition has evidence.
3. Every release transition identifies the exact artifact.
4. Every claim has a bounded scope.
5. Every external execution claim identifies its execution authority.
