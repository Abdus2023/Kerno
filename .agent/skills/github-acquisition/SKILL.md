---
name: github-acquisition
description: Acquire a repository only after verifying the remote ref matches the requested exact commit and tree.
---

# GitHub Acquisition

This adapter is an acquisition boundary, not a trust oracle.

## Required input

- repository
- ref
- exact commit
- exact tree

## Procedure

1. Resolve the remote ref.
2. Compare returned commit and tree with the requested snapshot.
3. BLOCK on any mismatch.
4. Enumerate the requested tree.
5. Fetch every blob at the pinned commit.
6. Sort paths deterministically.
7. Return the immutable acquisition result.

## Guarantees

The adapter can establish that the retrieved files correspond to the requested remote snapshot **only to the extent established by the acquisition authority**.

It must not claim:
- CI execution
- test execution
- runtime behavior
- deployment state
- security properties not observable from the acquired tree

An acquisition failure is evidence of acquisition failure, not evidence that the repository is absent or defective.
