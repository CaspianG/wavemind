# v2: native six-setting readout and an off-grid audit

2026-09-08. This is a new, explicitly post-v1 hypothesis. The old blind
spots and failed uniform-readout claim remain in the evidence. The v1
leading-order leakage theorem is not extended to finite coupling here.

## What changes physically

Keep the signed-pulse control, input |+x>, and three-level ladder. Append
one of six nominal Pauli-analysis settings, followed by the SAME native
bright-state detector. Settings use 0, pi or pi/2 control angles about X/Y.
These are not perfect basis projectors in the main test: their finite
pulses couple to the spectator and share the sensing amplitude/detuning
errors. Signal and spectator phase continue during the whole analysis.
All settings occupy a common window t_p, padded symmetrically with idle
time. No second carrier, perfectly selective spectator gate, erasure flag,
postselection or free quantum-state tomography is assumed.

The detector has two outcomes with click effect

    E = p_dark I + c |0><0|,  c=p_bright-p_dark,
    p_dark=0.07, p_bright=0.10.

These are synthetic photon-click probabilities, not measured NV parameters.
Primary noise is isotropic qutrit depolarization. Because that channel
commutes with every unitary, evolution with constant depolarizing rate is
exactly rho(T)=v U rho(0) U^dagger+(1-v)I/3, with v=exp(-0.2).
An additional stress test uses phase damping DURING the pulses instead.
Neither model substitutes for a characterized device's noise spectrum.

For setting j, use F_j=(d p_j/db)^2/[p_j(1-p_j)]. Report

    information rate = (sum_j F_j / 6) / (N tau + t_p + overhead).

Six directions do not grant six times as many shots. Every known baseline
gets the same analysis pulses, detector and time budget. The randomized
XY8 baseline averages 32 fixed phase realizations with their identities
retained in the statistical record; its shots are divided, not multiplied.
The metric is conditional on calibrated nuisance parameters and detector
probabilities. Joint estimation of field, drift and calibration errors is
not being smuggled into a single-parameter Fisher score.

## Known ideal-readout identity, not a new discovery

For the IDEAL analysis-only comparison, write the unnormalized qubit block
as rho_Q=(s I+r.sigma)/2. Its six ideal projectors have probabilities
p_(k,+/-)=p_dark+c(s+/-r_k)/2. Differentiating with respect to the field,

    sum_(k,+/-) (p'_(k,+/-))^2 = c^2 (3(s')^2+||r'||^2)/2.

Since p(1-p)<=p_bright(1-p_bright) for these detector parameters,

    F_average >= c^2 [3(s')^2+||r'||^2]
                 / [12 p_bright(1-p_bright)].

Thus a nonzero derivative of the accessible qubit block cannot be hidden
from ALL ideal directions simultaneously. It does NOT protect a tangent
carried solely by qubit–spectator coherences: |0><2|+|2><0| is an explicit
counterexample to a full-qutrit claim. Finite analysis errors also require
their own test; the ideal identity is not applied to imperfect projectors.

Complete mutually unbiased measurements and frame identities are established
tools, not a novelty claim. See [Scott, section IV, complete MUB construction](https://arxiv.org/html/quant-ph/0604049).
That discussion concerns informational completeness in the stated dimension;
our six ideal projectors do NOT form a complete qutrit measurement.

## Continuous spectator-detuning audit

Let x=Delta/(2*pi), T=N tau+t_p, and v_j(x)=d p_j/db for the six physical
readouts. To avoid missing zeros between grid samples, bound the vector
v=(v_1,...,v_6), not just the squared Fisher score.

For unitary propagation, subtracting (Delta/2)I changes only global phase.
The remaining detuning derivative has operator norm 1/2; the field
derivative has norm |cos(pi*t)|/2. Define

    B = (1/2) integral_0^T |cos(pi*t)| dt.

Ordered-integral bounds give ||U_(x^k b^l)|| <= (pi*T)^k B^l for the
mixed derivatives needed here. Expanding p=|<0|U|+x>|^2 by the product
rule gives a conservative scalar bound

    |d^2 v_j / dx^2| <= c v_dep 8 (pi*T)^2 B,
    ||v''||_2 <= sqrt(6) c v_dep 8 (pi*T)^2 B = M.

The coefficients and pulse times do not depend on x, an essential
assumption. The same T applies to every analysis setting. Isotropic
depolarization multiplies all field slopes by v_dep; its rate is fixed,
not differentiated with x or b.

On [a,b] of width h, the norm distance between v and the linearly
interpolated endpoint vector is <= M h^2/8. Minimize the norm of that line
segment analytically. Subtract M h^2/8 and the declared endpoint numerical
error allowance. A positive remainder L gives the interval lower bound

    information rate >= L^2 / [6 p_bright(1-p_bright)(T+overhead)].

Bisect uncertified intervals, without choosing new pulse phases or dropping
unfavorable intervals. Exhausting the fixed point budget means UNRESOLVED,
not pass. This covers the continuous x range for nine FIXED error pairs,
not all intermediate amplitude/frequency errors. Endpoints use floating
linear algebra with a conservative declared error allowance. The resulting
enclosure is CONDITIONAL on that allowance, not certified interval arithmetic.

## Nearby mechanisms already known

- [Wang et al., PRL 122, 200403, phase randomization](https://discovery.ucl.ac.uk/id/eprint/10083242/1/Monteiro_Randomization%20of%20Pulse%20Phases%20for%20Unambiguous%20and%20Robust%20Quantum%20Sensing_VoR.pdf):
  the RXY8 baseline adds a random block-global phase. It is not our invention.
- [Niroula et al., PRL 133, 080801, pp. 1–2](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=956748):
  detecting erasures can change attainable information scaling. Our native
  binary clicks neither implement nondemolition erasure detection nor inherit
  that paper's guarantee for coherent pulse-induced leakage.
- [Ni–Sun, sections III.1–III.2](https://arxiv.org/html/2608.06119v1):
  deterministic averaging of Hadamard phase patterns is already proposed.
  Distinguish preparation/control phase averaging from this readout change;
  neither is intrinsically a new principle.

The only still-open priority question in this line is the precise signed
pulse, arbitrary-input first-order leakage bound in THEORY.md and any
nontrivial physically useful extension. Bounded RS/Golay/NMR/pulse-control
searches have not resolved it. No absence-of-results claim establishes
priority, and no independent review has occurred.

## Admission is not a software-test count

Removing the eight old blind spots would be progress, not a scientific
breakthrough. The new frozen protocol also requires a meaningful matched-
budget comparison, exposes median regressions, and includes a different
noise-model stress. Physical calibration, a realizable preparation/readout
setup, nuisance identifiability, frequency/phase coverage, and independent
defect-diagnosis data remain required for a useful device or mass-market claim.
