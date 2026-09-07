# R8: REJECTED. NO QUALIFYING CANDIDATE.

2026-09-07. One user-authorized decisive review, based on the compact packet
at `8bb5adb926c9d2b9bc021dda95610d21cb6cfca2` and the primary sections cited
below. No independent review, external model invocation, paid endpoint,
hardware, publication or terms approval. The requested mode was MAX; no
separate runtime-setting verification is available, so this record does not
claim to have switched models or reasoning settings.

## Binary decision: REJECTED

**Close R8 as a candidate for the original scientific/practical objective.**
This is an internal admission decision, not a claim that the mathematical
recognizer is false, that an exact earlier CSS theorem was located, or that
an independent reviewer applied the packet's conditional novelty-kill rule.
The current evidence does not defend the required conjunction of novelty,
nontriviality and practical significance. No more R8 tests/search are queued.

### Correctness and novelty attacked first

The core lemma withstands the direct algebraic attack: on a scalar atom,
trace one gives I+T^2+T=diag((1+det T_j)I), a preserving scalar mask. It must
be either 0 or I throughout that atom. A rank-one anchor therefore forces
rank one everywhere. This is a short consequence of Cayley–Hamilton and the
known scalar-atom decomposition, not evidence of an independent invention.
The two-Bell control breaks a missing-atom hypothesis, not this statement.
The F4 control only breaks arbitrary-idempotent substitution.
[Mirandola–Zémor, §2.3, Lemmas 2.7/2.10](https://arxiv.org/html/1501.06419v2).

The stronger competing reduction does not use the six-anchor lemma:

1. The supplied two-dimensional modules jointly give a faithful action.
   The kernel K of their composition-factor actions is strictly triangular
   on each reducible module and zero on irreducibles, so K^2=0. The radical
   annihilates simple factors and every nilpotent ideal is radical: K=J.
2. All simple factors of E/J are visible and have simple binary modules of
   dimension at most two: only F2, F4 and M2(F2) remain.
3. F4 cannot supply rank one. A primitive M2 idempotent has rank one in every
   equivalent natural module. Shared F2 characters require x_a XOR x_b=1;
   repeated characters or an odd cycle are genuine rank obstructions.
4. Distinct simple-module kernels are distinct maximal two-sided ideals;
   the simultaneous simple action is onto their product. Hence compatible
   selected values have a preimage a. Since a^2+a is in J and J^2=0,
   a^4+a^2=0: e=a^2 is an idempotent. Ranks add over the physical composition
   series; no characteristic-two trace shortcut is used.
5. Diagonalize the physical blocks. This gives the same unknown-target CSS
   decision/witness, without a supplied CSS target or maximal-rank completion.

These are local deductions from ordinary algebra, not quotations of a CSS
theorem. The needed effective structure interface is explicit in
[Brooksbank–Wilson, §2.2, Theorem 2.5 / Remark 2.1, pp. 6–7](https://www.researchgate.net/publication/228776809_Computing_isometry_groups_of_Hermitian_maps).
The original Rónyai text and publication priority of the exact specialization
remain gaps; neither is evidence for novelty. The deterministic small-module
route in the packet uses only three possible invariant lines, four-variable
intertwiner systems and ordinary elimination after building E. No essential
new recognition lemma was identified. Its exact cost remains a paper argument,
not an executed SOTA comparison or independently validated result.

Six-certificate formatting is not an established complexity separation.
The CSS/projector bridge is also explicit in
[Albert, Appendix F.2, proof of Lemma F.2, equations 186–189](https://arxiv.org/html/2608.05688v1).
Moreover, relabeling a code and its noise/decoder together preserves logical
outcome probabilities by a bijection of errors; keeping biased physical noise
fixed gives no automatic improvement. R8 specifies neither a new extraction
circuit nor a measured decoding/workflow advantage. Thus even a useful
correct recognition corollary does not satisfy this mission's candidate bar.

## Exactly one alternative attempt: raw compressed shared flags

**Attempted mechanism/claim.** Encode a propagating syndrome-ancilla fault's
location j as binary(j) in a shared flag register, omit spatial protection of
the flag bits, and still leave at most one data error (modulo stabilizers)
after any one circuit/readout fault. The minimal test is three flags for a
weight-eight check of the [[15,7,3]] CSS Hamming code. All ordinary stabilizer
syndromes are allowed; there is no extra distinguishing flag record.

Encoded flags and sharing across checks are already known. The attempted
distinction is removing protection while retaining one-fault tolerance, not
renaming those methods. [Anker–Marvian, §§II–III, Definitions 1–3 and equation 1](https://arxiv.org/html/2212.10738v2)
explicitly models syndrome propagation F e_s XOR e_f, including false flags,
and protects flag constructions using classical-code checks. Its introduction
describes shared gadgets and spatial repetition. The HTML stops in §III;
later proofs were not claimed as read. Protected logarithmic flag patterns
also predate this attempt: [Prabhu–Reichardt, §3.2, Theorem 4 and proof](https://arxiv.org/html/2108.02184v2).

**Intended outcome, not evidence:** fewer auxiliary qubits per reliable QEC
operation could reduce resource cost for quantum-cloud users and enterprise
jobs. No mass adoption, enterprise task benefit or tenfold advantage is
established. The attempted physical fault-handling guarantee fails first.

### Decisive local falsifier: executed, claim refuted

Let the four X and four Z checks use the parity-check columns 1,...,15 of
the binary Hamming code. Measure X on sites 8,...,15 in that order. Compare:

- One X fault on the syndrome ancilla after the fourth data CNOT: data error
  E=X12 X13 X14 X15, with raw location flag binary(4)=100.
- One flipped flag readout bit: data error I, with the same flag 100.

E has zero syndrome for all eight stabilizers, but is not a stabilizer. Its
minimum weight modulo X stabilizers is four. The records are identical, so
any correction R must work for both I and E. If both residuals had weight
at most one, E would have stabilizer-coset weight at most two: contradiction.
This already proves failure; the executable exhaustively cross-checks it.
It also checks the code's commutation, rank and distance-three conditions.

```sh
python research/breakthrough/shared_flag_collision_falsifier.py
```

Expected: `RAW_SHARED_FLAG_CLAIM_REFUTED`; 32,768 X corrections exhausted;
**0** common corrections with both residual weights <=1; minimum worst
residual weight **2**. General Pauli corrections cannot help: their X
component already fails this necessary condition. This was a derived
counterexample before execution, not held-out discovery or hardware data.

Script SHA-256: `ba47131dfbed4e843eb531ddf40562583109d7616c97f9f1f7f999019b444dcf`.
The two fault scenarios are sufficient under the claimed propagation map;
changing the map or protecting the readout changes the construction. No such
second attempt is made. This does not refute R8 or protected flag protocols.

## Stop condition

R8 is closed; the single alternative is refuted: **NO QUALIFYING CANDIDATE**.
Existing R8 evidence and the packet at 8bb5adb are preserved. No R8 suite
rerun, decorative benchmark, new review packet or further search follows.
Both mission gates stay false. Human terms status is untouched.
