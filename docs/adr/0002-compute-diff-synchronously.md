# Compute MVP diffs synchronously

The MVP `GET /workspaces/{ws}/diff` resolves immutable Revision inputs, returns a cached report when available, and otherwise computes and persists the complete requested report before responding. The UI owns the transient loading state and the service emits `diff/ready` only after persistence; no job table, task ID, background queue, or polling contract is introduced. This keeps the API small under the three-second L3 target while preserving a later option to add an explicitly versioned asynchronous protocol if real workloads require it.

