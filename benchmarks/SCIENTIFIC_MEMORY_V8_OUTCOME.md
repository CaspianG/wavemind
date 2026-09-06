# Scientific memory v8 outcome

Status: `failed_development_gate_v8`.

The frozen v8 candidate failed its first MemoryAgentBench development run.
Across five independent Accurate Retrieval contexts, one paired effect was
positive, three were zero, and one was negative. The paired cluster-bootstrap
mean was `0.0`, with a 95% confidence interval of `[-0.6, 0.6]`; the frozen
rule required the lower bound to be strictly greater than zero.

The intervention was present on every case, the production index remained
empty, and there were no promotions. Phrase-first ranking therefore introduced
a measured regression on one development context and did not deliver net
task-success uplift.

Runs two and three and all later v8 gates were not opened. The five opened
contexts may inform a successor as development evidence but may never be reused
as its gate. Validation, final, and LongMemEval-V2 evidence remains untouched.

No v8 validation, admission, product-superiority, SOTA, production-promotion,
100%-pass, or revolutionary claim is permitted.
