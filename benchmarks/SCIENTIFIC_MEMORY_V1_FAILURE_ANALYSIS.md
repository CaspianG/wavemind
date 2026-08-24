# Scientific memory v1 failure analysis

This document preserves the v1 result as negative evidence. It does not reopen,
rename, or overwrite the terminal `failed_experiment` package.

## Confirmed validity defects

1. All six MemoryAgentBench rows recorded zero selected memories and zero
   selected tokens. Treatment and control therefore received byte-identical
   prompts. Model nondeterminism, not memory, caused any answer differences.
2. The two reported MemoryAgentBench "contexts" had the same context SHA-256.
   They were duplicate rows, not two independent clusters.
3. Graph and causal candidates both fell back to the same generic relevance-only
   `shadow_recall`. Their benchmark treatment mechanism was therefore identical,
   despite different registered candidate identities.
4. MemOps used only subject A04, so a cluster confidence interval was impossible.
5. The A04 memory exposed a fact after an explicit user deletion request. This
   caused the two negative Forget effects and demonstrates missing tombstone and
   state-reconciliation semantics.

## v2 causal hypothesis

The failure is not addressed by changing a score threshold. The v2 hypothesis is
that memory must be compiled into source-ordered typed state, reconciled before
retrieval, and audited for a real treatment intervention. Duplicate fingerprints
must be collapsed to one statistical cluster. This hypothesis is frozen in
`scientific_memory_protocol_v2.json` before the first v2 outcome is generated.
