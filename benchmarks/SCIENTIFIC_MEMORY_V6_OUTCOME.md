# Scientific memory v6 outcome

Status: `failed_admission_v6`.

The frozen v6 candidate passed its bounded development gate, but it did not
generalize to the first preregistered held-out validation family. On five
independent MemoryAgentBench validation contexts, all five paired effects were
zero. The paired cluster-bootstrap mean was `0.0` with a 95% confidence
interval of `[0.0, 0.0]`; the frozen gate required the lower bound to be
strictly greater than zero.

The intervention was present on every case, the production index remained
empty, and there were no promotions. This is therefore a genuine absence of
measured task-success uplift, not a missing-intervention or safety failure.

The remaining MemOps validation and full LongMemEval-V2 held-out evidence were
not opened. Once the first mandatory validation family failed, they could not
change the preregistered v6 decision and were preserved for a future protocol.
The five opened MAB validation contexts are permanently forbidden for tuning.

No v6 admission, product-superiority, SOTA, production-promotion, or
revolutionary claim is permitted.
