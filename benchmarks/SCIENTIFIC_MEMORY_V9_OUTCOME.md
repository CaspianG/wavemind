# Scientific memory v9 outcome

Status: `failed_development_gate_v9`.

The frozen v9 candidate failed its first DetectiveQA development run. Across
five independent contexts, four paired effects were zero and one was negative.
The paired cluster-bootstrap mean was `-0.2`, with a 95% confidence interval of
`[-0.6, 0.0]`; the frozen rule required the lower bound to be strictly positive.

Intervention coverage was complete, production storage remained empty, and no
memory was promoted. The query-constrained transducer did not create positive
effects on this source, while additional retrieved context caused one measured
regression.

Runs two and three and all later v9 gates were not opened. The five opened
contexts may inform a successor but may not be reused as a gate. Validation,
final, and LongMemEval-V2 evidence remains untouched.
