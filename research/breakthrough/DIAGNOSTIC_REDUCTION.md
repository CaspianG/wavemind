# Diagnostic transport: reduction to existing decision theory

2026-09-06 continuation. The previous turn made progress: three frozen runs
changed the candidate decisions and preserved raw negative evidence.

The next proposed idea was to carry a small set of diagnostic witnesses with
a learned procedure. In a finite, stationary hypothesis model, this reduces
directly to known decision-region determination. It is not a new scientific
mechanism merely because the tests are stored as memory.

Let h be a possible current environment, e a diagnostic test, and a a stored
procedure. Let R(a) be the environments in which a succeeds. Observations S
leave a version space V(S). A noiseless witness certifies a exactly when
V(S) is a subset of R(a). Selecting tests until that condition holds is the
problem in [Javdani et al., AISTATS 2014, sections 2–3](https://proceedings.mlr.press/v33/javdani14.pdf).
The paper permits overlapping decision regions; identifying the entire
environment is unnecessary. That already covers the supposed distinction
between a reusable safe action and a complete world model.

[Cicalese et al., ICML 2014](https://proceedings.mlr.press/v32/cicalese14.pdf)
also treats diagnosis trees with worst-case and expected costs. Consequently,
beating indiscriminate entropy reduction does not by itself establish novelty
or a new capability. Prior work explicitly distinguishes those objectives.

With noisy conditionally independent tests, replace V(S) by posterior b.
For finite remaining horizon r and specified losses, exact Bayes dynamic
programming gives

    V(b,0) = min_a sum_h b(h) loss(a,h)
    V(b,r) = min { V(b,0), min_e [cost(e) + sum_y P(y|b,e) V(b_e,y,r-1)] }.

This is a baseline for the declared model and horizon. It is not a universal
lower bound over unknown real physics. It assumes the world remains fixed
during probing, calibrated likelihoods, specified prior/losses, and no hidden
side effects. The Bayes posterior already retains all relevant history under
these assumptions. A memory method given the same information cannot beat
the optimum here; it could only compute an equivalent policy more cheaply,
or win in a different, explicitly specified model.

`diagnostic_oracle.py` implements this recurrence with exact rational numbers,
and tests it against enumeration of all deterministic policy trees at depth
two. This is research infrastructure, not a claimed candidate breakthrough.
The registered sweep maps when a single fresh witness is insufficient and
sets a strong baseline for later mechanisms.

## Closest additional frontier art

[Bayesian ACRONYM, TQC 2019](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.TQC.2019.7)
already uses smoothness to transfer quantum-control information.
[Adaptive online quantum-state learning](https://arxiv.org/abs/2206.00220)
and [optimal causal intervention design](https://arxiv.org/abs/2209.04744)
are relevant adjacent source leads; only their abstracts were retrieved in
this pass, so their precise limitations still need full-text review.

Current quantum-control work also reuses QEC detection events to stabilize
control parameters: [Sivak et al., Nature 2026](https://www.nature.com/articles/s41586-026-10759-2).
The primary indexed page was found but direct full-page access failed. It is
not counted as a fully reviewed paper or reproduced experiment.

## Surviving research gap, not yet a new assertion

The remaining question must involve something the fixed-model reduction does
not provide: reliable learning of transport structure, model misspecification,
physical measurement backaction, or a provable resource separation in policy
construction. Each has substantial prior art. Before choosing one, obtain
full-text closest work and an externally authored problem whose assumptions
cannot be tailored to the candidate. Do not turn an exact small-model success
or a new cache name into a claim of fundamental progress.
