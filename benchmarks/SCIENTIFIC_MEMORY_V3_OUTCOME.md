# Scientific memory v3 development outcome

Status: `failed_experiment_v3_runtime_budget`

The frozen v3 run at source SHA
`eea3fc63a4720b159445224567dfc751bd5e2960` was stopped after more than
30 minutes because it had already violated the frozen runtime gate. No raw score
or result artifact was produced, so no accuracy or uplift claim is made.

The retained external scratch directory is:

`C:\Users\LEO\Documents\Codex\2026-08-16\ct\scientific-evidence\runs\mab-v3-accurate-pilot-eea3fc6`

At termination it contained 14 files totaling 693,190,192 bytes. The five main
legacy vector databases were 84,172,800; 230,985,728; 11,350,016; 15,712,256;
and 320,176,128 bytes. The corresponding append-only scientific event stores
were retained. The Python process remained responsive and CPU-active; this was
a performance failure, not a crash.

Root cause: every blind-compiled structural unit was written both to the
scientific event log used by v3 selection and to the legacy vector substrate
that v3 selection did not use. Rebuilding that redundant substrate dominated
runtime and storage. A candidate that removes this duplicate indexing path is a
new implementation and therefore requires a new protocol version before any
new outcome.
