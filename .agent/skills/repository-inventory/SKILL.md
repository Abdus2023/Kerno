---
name: repository-inventory
description: Normalize a repository file tree into a deterministic inventory bound to an exact snapshot.
---

# Repository Inventory

The inventory is the boundary between repository access and static audit.

Required identity:
- repository
- ref
- exact snapshot commit

The inventory must preserve file paths and, when available, content or content digests.

The inventory adapter does not infer repository behavior.

## Composition

`repository inventory → repo audit → evidence records → verification gate`

An empty inventory is BLOCKED.

Generated timestamps describe observation time; they do not replace snapshot identity.
