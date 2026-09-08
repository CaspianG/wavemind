# v3: suppress leakage within a pulse, then test the sequence contribution

2026-09-08. This is a new experiment, not a correction of v2's failed gate.

The physical hypothesis is that smooth quadrature compensation reduces the
spectator excitation produced by each pulse; RS coding could then control
residual accumulation. Crucially, every baseline receives the same pulse
shapes. A win over an unnecessarily weak rectangular reference would not
establish an RS contribution or a scientific breakthrough.

## Known foundation and our convention

DRAG uses a derivative quadrature and a frequency correction. This is an
established control mechanism, not an invention of this repository.
[Motzoi et al., PRL 103, 110501, equations 9 and 10](https://harvest.aps.org/v2/journals/articles/10.1103/PhysRevLett.103.110501/fulltext).
That paper's superconducting-qubit gate improvements are not sensing results
for our model. We use its leading derivative/detuning terms and cubic
in-phase correction, not its full fifth-order pulse or optimized parameters.
Multi-derivative extensions also already exist:
[Li et al., npj Quantum Information 10, 66 (2024)](https://www.nature.com/articles/s41534-024-00863-4).

The three-level model, initial state, signal and detector are inherited from
v2. During a pulse we add longitudinal control d(t) diag(0,1,2), and replace
the common nearest-neighbor RF drive by

    H_01 = (1+epsilon) [X(t)-iY(t)] exp(-i phi) / 2,
    H_12 = eta H_01.

The diagonal is (delta_q/2, -delta_q/2+d, Delta+2d), with the same
b cos(pi t) Z/2 signal. The longitudinal control is an additional physical
capability; its cost and required calibration must not disappear under the
phrase "virtual frame". Hardware implementation has not been demonstrated.

For u in [0,t_p], let A=(pi/t_p)[1-cos(2*pi*u/t_p)], Delta_0=28*pi,
and lambda_0=1. Define the fixed DRAG3 waveform:

    X = A + (lambda_0^2-4) A^3 / (8 Delta_0^2),
    Y = -A_dot / Delta_0,
    d = (lambda_0^2-4) A^2 / (4 Delta_0).

No coefficients are fitted to the new data. HANN uses X=A, Y=d=0. RECT and
FAST_RECT use a rectangular pi pulse of width .25 and .125 respectively.
All pulses remain centered at j+.5. The narrow rectangular reference can
use the higher RF peak available to the shaped pulses.

## Resource contract

Every method has the same nominal RF peak cap 8.1*pi, RF energy cap
8*pi^2 per pulse, and |d|<=6. Caps are equal; consumed energy need not be.
For the Hann envelope at t_p=.25, integral A^2 dt=6*pi^2. Since the cubic
correction only reduces X in this regime, DRAG3's RF energy is bounded by

    6*pi^2 + [ (32*pi^2)^2 * .25 / 2 ] / Delta_0^2 < 8*pi^2.

Its peak obeys sqrt((8*pi)^2+(32*pi^2/Delta_0)^2)<8.1*pi, and
|d|<=3*(8*pi)^2/(4*Delta_0)<6. RECT uses 4*pi^2, FAST_RECT uses 8*pi^2.
The possible 2% RF amplitude error is applied equally to both quadratures;
the longitudinal coefficient remains nominal. Calibration and bandwidth
are assumptions, not device measurements. All methods use the same finite
analysis pulses and total duration 74.25 including assumed overhead.

## Computation and limits

For constant RF phase phi, D=diag(exp(-i phi),1,exp(i phi)) conjugates the
zero-phase Hamiltonian to H_phi. It commutes with the signal and diagonal
controls. Thus pulse propagators and signal derivatives can be computed
once per waveform/error and conjugated for each phase, including RXY8.
This is an exact symmetry of this model, not a physical speedup claim.

Within each pulse, piecewise-constant midpoint controls are integrated by
unitary matrix exponentials. Each segment's weak-field derivative uses
the exact spectral integral, including the oscillating signal. Idle
evolution and the v2 analysis tail are included. Numerical convergence
must be checked; the shaped waveform is not analytically time-integrated.

The new grid is the 1024 cell midpoints of [12,16], disjoint from the v2
grid. The same nine calibrated error pairs are retained. No optimizer or
selection on these new outcomes is allowed. The v1 first-order theorem
is NOT asserted for these new pulse shapes; the v2 conditional continuous
cover is NOT reused for v3. Single-parameter FI still conditions on known
calibration and known signal frequency/phase. A positive finite-grid
result would need further falsification, independent priority review and
device/workflow measurements before any broader admission.
