# Agent execution layer

The files in this directory are intentionally small and deterministic. They define the orchestration contract; platform adapters execute the individual operations.

The canonical command sequence is:

```
snapshot -> audit -> evidence -> verify -> design -> plan -> gate
```

No command is allowed to upgrade a status without evidence.
