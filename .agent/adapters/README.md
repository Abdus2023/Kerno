# Adapter contract

Adapters are evidence-producing boundaries between the workflow runner and an execution authority.

Required output:

```json
{
  "stage": "string",
  "status": "COMPLETE|BLOCKED|FAILED",
  "authority": "string",
  "output_digest": "string",
  "evidence_ids": ["string"],
  "blockers": []
}
```

An adapter MUST NOT report COMPLETE without evidence. It MUST identify the authority that produced the evidence.

Adapters are deterministic with respect to their declared input snapshot. Nondeterministic sources must record observation time and source identity.
