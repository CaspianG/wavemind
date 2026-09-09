# Post-screen off-grid falsification protocol

2026-09-07. This protocol was written AFTER inspecting `runs/v1`.
It is a diagnostic follow-up, not a preregistered holdout or a replacement
for the preserved original experiment.

The initial finite-grid minimum-rate ratio is approximately 688.09 relative
to XY8, the strongest minimum among six implemented conventional protocols.
However, the saved candidate `dp_db` array contains eight sign changes along
spectator detuning. Fisher information squares this derivative and hides
the sign changes. Consequently the grid comparison can miss blind spots
between adjacent samples. It is NOT a uniform robust-sensing guarantee.

## Frozen follow-up

1. Verify the stored v1 checksums and protocol/source hashes. Do not edit,
   rerun in place or remove the first result.
2. Enumerate ALL sign-changing adjacent-detuning intervals in each of the
   nine candidate error settings; no choice of a flattering interval.
3. Bisect each interval 32 times using the same exact signal derivative.
   Save both original endpoints, the final bracket, outcome probability,
   slope, FI per total cycle, and pure-state quantum Fisher information.
4. At the FIRST interval in array order, check both ORIGINAL endpoint
   derivative signs using the separate finite-signal midpoint propagator,
   128 and 256 slices per pulse and b=+/-1e-5/N. Require agreement within
   3e-6*(1+abs(exact slope)) and preserved opposite signs. The final
   sub-picounit bracket is numerical localization, not interval-arithmetic
   certification of all its digits.
5. Evaluate all six conventional baselines and the raw-RS ablation at the
   first localized candidate root. This is an adversarial diagnostic at a
   selected root, not a new aggregate benchmark.

If the endpoint signs remain opposite, analyticity/continuity of the
finite-dimensional propagator implies a zero local response between them
in this specified model. A nonsingular probability there makes the binary
local FI zero. A large quantum FI does not rescue this readout: it instead
distinguishes a measurement blind spot from loss of all state information.
Do not claim this refutes the first-order leakage bound, every readout,
every pulse-coded sensor, or all finite-amplitude distinguishability.

Neither the numerical grid pass nor a zero-slope counterexample changes
the unclosed novelty, hardware, and consumer/enterprise gates. A different
readout, pulse protocol, domain, or threshold would be a NEW hypothesis,
not a repaired v1 result.
