# Signed-pulse leakage bound — candidate calculation, not a discovery claim

2026-09-07. New quantum-sensing investigation. This does not reopen R8.
The following derivation is local work using known Rudin–Shapiro (RS)
polynomials. Neither priority nor practical advantage is established.
The frozen experiment is [protocol.json](protocol.json).

## Exact claim and its limits

Use basis |0>, |1> (sensor), |2> (spectator), hbar=1. During pulse j,

    H_j = Delta |2><2| + s_j Omega/2
          (|0><1| + |1><0| + eta |1><2| + eta |2><1|).

Between pulses only the spectator phase evolves. Rectangular pi pulses have
duration t_p=pi/Omega, centers (j+1/2) tau, and 0<t_p<=tau. There are N=2M
pulses, N a power of two >=4, total time T=N tau. The first/last free
intervals have length g=(tau-t_p)/2. This is a ladder model, not a full NV
Hamiltonian or a replication of a published sensing experiment.

Let r_j=(-1)^(number of overlapping `11` pairs in the binary expansion of j),
and choose s_j=r_j r_(j+1), not s_j=r_j. Define the row

    K = d/deta [ <2| U_eta(T) (|0>, |1>) ] at eta=0.

For ANY input state in the sensing subspace and ANY real spectator detuning,

    ||K|| <= a sqrt(N) + c,
    a = (Omega/2) |I_s - exp(-i Delta tau) I_c|,
    c = Omega |I_c|,
    I_c = integral_0^tp exp(i Delta u) cos(Omega u/2) du,
    I_s = integral_0^tp exp(i Delta u) sin(Omega u/2) du.

In particular a,c<=2, so ||K||^2 <= 4(sqrt(N)+1)^2. This bounds the
LEADING leakage coefficient, not leakage for arbitrary coupling or signal.
It does not assert that all pulse-induced errors, or all noise, disappear.

## Derivation to be attacked by the exact propagator

1. Before pulse j the ideal qubit propagator is a_j X^j with
   a_j=(-i)^j product_(k<j) s_k=(-i)^j r_j. First-order perturbation theory
   gives, apart from the common factor -i(Omega/2) exp[-i Delta(T-g)],

       sum_j z^j (-i)^j
       [r_(j+1) I_c <1| X^j - i r_j I_s <0| X^j],
       z=exp(i Delta tau).

   The prefix product is essential. A flat scalar phase sequence cannot
   simply be substituted for this two-component quantum amplitude.

2. The RS identities are r_(2k)=r_k and r_(2k+1)=(-1)^k r_k. With
   w=-z^2, P(w)=sum_(k=0)^(M-1) r_k w^k and
   S(w)=sum_(k=0)^(M-1) r_(k+1) w^k, the two row components become

       B_0 = -i [I_s P(w) + z I_c S(w)],
       B_1 = (I_c-z I_s) P(-w).

3. For dyadic M, r_0=r_M=1, hence S(w)=[P(w)-1+w^M]/w. Put
   A=I_s-I_c/z. Then

       B_0=-i [A P(w) + z I_c (w^M-1)/w],
       B_1=-z A P(-w).

   The finite-train boundary term must not be dropped.

4. The familiar complementary-polynomial identity implies
   |P(w)|^2+|P(-w)|^2=2M=N for |w|=1. One can verify this form directly:
   P_(2L)(w)=P_L(w^2)+w P_L(-w^2), and induction on dyadic L doubles
   the norm sum. The first vector in step 3 therefore has norm |A|sqrt(N);
   the boundary vector has norm <=2|I_c|. Triangle inequality proves the
   claimed bound. At w^M=1 the boundary vanishes and
   ||K||^2=(Omega/2)^2 |A|^2 N exactly.

5. Since sine/cosine are nonnegative on this half Rabi cycle,
   |I_c|,|I_s|<=2/Omega. This yields the detuning-independent coarse bound.

The underlying flat-polynomial mathematics is not new. See
[Benedetto–Sugar Moore, Definition 1.1 and Remark 1.4(a)](https://math.umd.edu/~jjb/benedetto_sugar-moore_2009.pdf).
That author's PDF uses pp. 449 onward; bibliographic listings also show
451–470. Section identifiers avoid that pagination discrepancy.

### Finite coupling: honest remainder, often unhelpful

The perturbation connects the two subspaces but has no within-subspace
blocks. Only odd Dyson orders enter the leakage row. Unitarity of the
unperturbed propagators gives the conservative norm remainder

    ||<2|U_eta P - eta K|| <= sinh(x)-x,
    x=|eta| N pi/2.

Thus leakage probability for every qubit input is at most

    min(1, [|eta|(a sqrt(N)+c) + sinh(x)-x]^2).

For large eta*N this is vacuous. In particular the result does NOT prove
linear-in-N physical leakage at fixed eta as N tends to infinity. Testing
eta=1 at large detuning below is an engineering stress test, not an
application of a uniformly accurate eta expansion.

## Signal and cost are separate questions

The test adds b cos(pi t/tau) Z/2 with Z=diag(1,-1,0), plus static qubit
detuning and fractional amplitude errors. The zero-coupling, zero-error
longitudinal toggling function is independent of the pi-pulse signs, even
for the rectangular pulses. At the chosen AC phase, the transverse
first-order contribution within each pulse integrates to zero by symmetry.
This predicts equal ideal weak-field response, not robustness at finite
signal amplitude or with a fluctuating/unknown signal phase.

The engineering screen uses |+x> preparation and the binary measurement
P_(+y), I-P_(+y). Leakage remains in the second outcome; there is NO
postselection. Compute dp/db at b=0 including signal action DURING pulses,
then F=(dp/db)^2/[p(1-p)]. Divide by N*tau+10*tau. The fixed overhead and
ideal preparation/readout are declared assumptions, not measured costs.
No photon noise, decoherence, temperature drift, ensemble distribution,
hardware bandwidth or SPAM errors are calibrated here.

## Nearest work and the unclosed novelty question

- [Lancaster et al., v1, Table 1 and sections III–IV](https://arxiv.org/html/2509.09874v1)
  studies sensing errors and spectator leakage, including a three-level
  ladder. It motivates testing signal response instead of coherence alone.
  Our classical-field toy model, arbitrary coupling parameter and
  state-independent leakage row are extensions, not reproduced data.
- [Wang et al., PRL 122, 200403, pp. 1–4](https://discovery.ucl.ac.uk/id/eprint/10083242/1/Monteiro_Randomization%20of%20Pulse%20Phases%20for%20Unambiguous%20and%20Robust%20Quantum%20Sensing_VoR.pdf)
  already uses block-global randomized phases to preserve a target response
  while suppressing artifacts and accumulated pulse imperfections. Phase
  modulation and incoherent error accumulation are not new claims here.
- [Ni–Sun, v1, sections II–III, equations 3–12](https://arxiv.org/html/2608.06119v1)
  deterministically averages outcomes over Hadamard phase patterns; its
  weak-coupling artifact-intensity factor is 1/M. A single-trajectory,
  worst-input qutrit leakage bound is a different stated object, but this
  distinction does not establish novelty or a cost advantage.

Targeted searches used RS/Rudin Shapiro with quantum control, dynamical
decoupling, pulse sequences, leakage and NMR; also Golay quantum sensing,
paperfolding dynamical decoupling, and randomized sensing phases. No exact
match was identified in those returned leads. This is NOT an exhaustive
priority search. Composite-pulse, Walsh/phase-coded control and leakage
elimination equivalence remain open. No patent clearance is implied.

## Intended utility, not an observed outcome

The physical target is reliable, cheaper magnetic inspection of electronics
and batteries. A recent
[endoscopic diamond-magnetometer study](https://arxiv.org/html/2606.18871v1)
demonstrates confined-space sensing and battery sheet-current reconstruction.
Its demonstrated readout is continuous-wave ODMR, not this pulse protocol;
it provides no validation of our method or of fault-detection accuracy.

For companies: test inspection time/cost at a fixed defect miss rate and
false-alarm rate on held-out devices. For people: test whether this improves
repair decisions or battery diagnosis, rather than merely producing a
cleaner magnetic trace. An order-of-magnitude measured workflow gain,
independent reproduction, and a device experiment remain required. No
claim of mass adoption, safety improvement or indispensability is admitted.
