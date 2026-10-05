# Agent workflow execution

The runner is intentionally conservative.

It may:
- validate state;
- select the next stage;
- persist RUNNING state;
- report the required adapter.

It may not:
- fabricate evidence;
- infer execution from source inspection;
- mark a stage complete without evidence;
- bypass a blocker;
- mutate the repository's protected release state.

Adapter implementations should be independently testable and should return:
`output_digest`, `evidence_ids`, `authority`, and `status`.
