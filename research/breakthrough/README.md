# Breakthrough research — active, not achieved

This is the research entry point for the mission started on 2026-09-06.
The released WaveMind product is an input to the investigation, not evidence
that a scientific breakthrough has happened.

Both gates remain required: a novel, independently reproducible scientific
capability and an order-of-magnitude or previously impossible improvement in
real consumer and enterprise workflows. External expert scrutiny is required
before calling any result a breakthrough. A local experiment cannot close
either gate.

- [Starting state and instruction audit](STATE_AND_AUDIT.md)
- [Primary-source novelty map and decision matrix](NOVELTY_REVIEW.md)
- [Frozen first experiment](protocol_r1.json)
- [Mechanism and proof boundary](MECHANISM.md)
- [Results and next decision](DECISION.md)
- [External baseline source pins](baseline_pins.json)
- [Diagnostic reduction and exact R4 baseline](DIAGNOSTIC_REDUCTION.md)

Results are recorded after execution, including rejection. No released runtime
is changed by this experiment. No paid API, judge, simulator, quantum hardware,
or LongMemEval execution is authorized by these local runners.

## Reproduce or audit

Python and NumPy suffice (`numpy==2.5.2` was used). Audit stored evidence:

```sh
python research/breakthrough/verify_evidence.py
python research/breakthrough/verify_r4.py
```

For reproduction, create a clean detached checkout at the run's source SHA
in `DECISION.md`, then invoke its `experiment_r1.py`, `experiment_r2.py` or
`experiment_r3.py` or `experiment_r4.py` with `--output` pointing to a new directory. Runners reject
existing output directories and tracked uncommitted changes. Preserve original
outcomes and record the reproducer's own environment and timing uncertainty.
