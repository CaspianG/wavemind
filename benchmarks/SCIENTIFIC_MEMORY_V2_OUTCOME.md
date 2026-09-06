# Scientific memory v2 development outcome

Status: `failed_experiment_v2`

The frozen v2 candidate was executed on five unique MemoryAgentBench
development-context fingerprints at source SHA
`1f620f131574c2e4a294d6af59c7bf67acd7ad6c`.

- Real intervention coverage: 5/5 (100%).
- Paired substring-exact-match effects: `[0, 0, 0, 1, 0]`.
- Mean effect: `+0.20`.
- Negative effects: 0.
- Cluster-bootstrap lower bound: `0`; therefore the strict positive-LCB gate
  was not passed.
- Raw SHA-256:
  `76294d1781497563d950586de6faafa39e5c4a60af43b9c48f089aeaec13ee0e`.
- Result SHA-256:
  `a477129de4f42b96126348b245ff29c8bd269490f8b650b9ea3e1bf6744d77e6`.

The treatment mechanism was finally non-null, fixing the central v1 validity
defect. Failure analysis showed a remaining representation error: the official
loader's large chunks contain many `Document N` units, so retrieval often found
the containing chunk but did not isolate the evidence-bearing document. The v2
candidate is frozen and will not be changed. Any hierarchical segmentation is a
new candidate and requires a new protocol digest.

The generated artifact's generic `reason_not_admission_eligible` says "single
development context" although five unique contexts were run. The explicit
`split_unit_ids`, `case_ids`, intervention audit, and raw rows correctly record
five contexts; the misleading generic string is retained rather than rewriting
the outcome after inspection.
