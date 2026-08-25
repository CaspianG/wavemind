# Scientific memory v4 development outcome

Status: `failed_experiment_v4_runtime_budget`

The frozen v4 run at source SHA
`59c0b96f90af0958dfa06f5c8469c26e76f8a013` was stopped after the
sequential event-log append path exceeded the runtime budget. No final raw score
or result artifact was produced, so no uplift claim is made.

Retained scratch:

`C:\Users\LEO\Documents\Codex\2026-08-16\ct\scientific-evidence\runs\mab-v4-accurate-pilot-59c0b96`

At termination the directory contained 14 files totaling 23,109,720 bytes.
Completed production databases were only 45,056 bytes each and contained zero
scientific records, confirming that v4 removed the v3 shadow-to-production
duplication. Scientific event logs were 2.7 MB to 6.6 MB for completed contexts.

Root cause: `ScientificEventLog.register_memory` reloads and validates the whole
chain and commits a `synchronous=FULL` transaction for every structural unit.
That preserves integrity but makes blind compilation approximately quadratic in
the number of units. The next candidate must append a prevalidated ordered batch
in one atomic transaction, produce the exact same per-event hash chain, roll
back the whole batch on any error, and preserve interleaved-writer safety.
