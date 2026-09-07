# R8: handoff for the next scientific gate

Read this page first. Do not rerun the entire investigation to recover scope.
This is a local proof candidate, not novelty clearance. The 2026-09-07
three-question audit found an explicit ordinary-finite-algebra reduction
to the required block ranks. **Do not prepare or run a new max-review packet
for polynomial recognition as a novel capability.** No external review was sent.

## Current decision after the three pressure points

1. **Rónyai/general algebra route:** the original full 1990 paper remains
   unavailable; it was not promoted beyond abstract-level coverage. A concrete
   structure interface was checked in Brooksbank–Wilson §2.2, Theorem 2.5 /
   Remark 2.1. Our explicit reduction selects rank 1 in M2(F2) factors,
   rejects F4 factors, and solves x_a XOR x_b=1 on the one-dimensional
   composition factors. On these physical modules Rad(E)^2=0, so any
   quotient-idempotent preimage a lifts by P=a^2. This fixes the previous
   missing correlated-rank/characteristic-2 step. A direct small-module
   specialization also gives a paper O(L n^2+n^4) bound without six anchors;
   it is not an executed or independently reviewed algorithm.
2. **Ivanyos–Qiao:** Proposition 32 can produce the needed projective ideal
   after the quotient rank choice; Fact 33 compares ranks, not selects them.
   Their main isometry/symmetrization route is not a char-2 drop-in. A local
   rank-growth proof-line issue is documented with an elementary repair;
   it does not refute their proposition or rescue our novelty claim.
3. **Pairwise graph algorithms:** the read equations require a supplied
   target and rank-n self-duality. Unknown CSS target and arbitrary code
   rank are not handled merely by adding their allowed linear constraints.
   No pairwise reduction was established; no impossibility theorem is claimed.

Full conditions, derivation, source links and bounded reading gaps:
[superseding theorem audit](PRIOR_ART_THEOREM_AUDIT.md).
Next: independent scrutiny of the explicit reduction (radical kernel,
simultaneous simple-action surjectivity, lift and complexity), not another
local R8 enumeration. Historical proof correctness remains a different
question from novelty. Six-anchor certificates alone are not an established
new capability. Both mission gates remain false.

## Exact R8 mathematical claim (not admitted as novel)

For L binary generators of an isotropic S <= F2^(2n), n >= 1, a deterministic
O(L n^2 + n^4) F2-operation algorithm decides whether **some** CSS form is
reachable by a tuple of independent single-qubit Cliffords and supplies a
positive transformation or six linear inconsistency certificates on a failing
scalar support. No second target code, ancillas or entangling maps are allowed.
The algebraic version also covers non-isotropic spaces, which are not physical
stabilizer codes. No speedup over an executed external SOTA solver is claimed.

## Proof spine and the exact pressure point

E = full algebra of site-local 2x2 maps preserving S. B = scalar masks in E.
Known Boolean-algebra atoms of B split S and E into independent supports.
On an atom the scalar algebra is {0,I}. For T in E with trace one at **every**
site, I + T^2 + T = diag((1 + det T_i)I2) is scalar in E. Hence determinants
are constant on the atom. Rank one at one anchor implies rank one everywhere.
Try the six trace-one/determinant-zero anchor blocks via linear systems;
assemble across atoms, then diagonalize to the X/Z projector. Under row
action P G = G diag(1,0), so closure yields the CSS decomposition.

The previously proposed novelty residue was the **recognition consequence**,
not scalar decomposition, Cayley–Hamilton, projectors or a noise guarantee.
The new ordinary-algebra reduction now prevents treating that residue as
having survived the novelty gate.
Detailed proof: [SCIENTIFIC_DECISION_GATE.md](SCIENTIFIC_DECISION_GATE.md).

## Source ledger and remaining coverage limits

1. [Mirandola–Zémor, §2.3 Lemmas 2.7/2.10](https://arxiv.org/pdf/1501.06419v2):
   scalar/code decomposition is already known and explicitly excluded.
2. [Rónyai, finite-algebra structure algorithms](https://www.sciencedirect.com/science/article/pii/S074771710880017X):
   original full text not obtained. The explicit reduction via the ordinary
   structure interface is now in the superseding audit; do not interpret
   the remaining bibliographic gap as survival of the novelty claim.
3. [Ivanyos–Qiao, §4.2–4.4](https://arxiv.org/pdf/1708.03495v3):
   Proposition 32 / Fact 33, proofs and small-field boundary now audited.
   Construction after quotient-rank selection is specified above. The F4
   shortcut counterexample does not refute this paper.
4. [Van den Nest–Dehaene–De Moor / Bouchet](https://arxiv.org/pdf/quant-ph/0405023)
   and [Claudet–Perdrix §3.1](https://drops.dagstuhl.de/storage/00lipics/lipics-vol334-icalp2025/html/LIPIcs.ICALP.2025.59/LIPIcs.ICALP.2025.59.html):
   fixed-target equations, self-duality, determinant constraints and restricted
   graph hypotheses audited. No direct arbitrary-rank/unknown-target reduction
   established; Bouchet's original full proof was not separately retrieved.
5. [Rains](https://arxiv.org/pdf/quant-ph/9703048),
   [Dasu–Burton](https://arxiv.org/html/2507.10519v1),
   [Albert Appendix F.2](https://arxiv.org/html/2608.05688v1):
   retain the uniform-map and already-known-projector overlaps. No novelty
   claim may rest on confusing uniform Cliffords with arbitrary local ones.
6. [Quantum XYZ, §III-D](https://arxiv.org/html/2607.14988v1#S3.SS4):
   matches the open question as described by those authors; not proof of priority.

Do not report papers as fully reviewed when only the listed sections/abstracts
were examined. The comparison details are in
[PRIOR_ART_THEOREM_AUDIT.md](PRIOR_ART_THEOREM_AUDIT.md).

## Evidence pins and remaining limits

- Original R8 source `fff2c991506344b7f69be6c4357bd52c1f91eb8b`: all 2,897
  small linear subspaces; all 549 isotropic cases are positive.
- Follow-up source `0692b111e141e4546a99c29a63359c2b935d46f4`:
  29,228 unital linear spaces, 519 algebras, 223 algebra negatives; ten n=7
  physical graph inputs, five negatives, including four indecomposable n=7
  negatives. All exact finite comparisons and full read-only replay passed.
- [Decision results](SCIENTIFIC_DECISION_RESULTS.md) records source/raw hashes
  and scope. These are local methods, not independent investigator replications.
- [Fixed-noise boundary](WORKFLOW_BRIDGE_AUDIT.md) rejects automatic practical
  improvement: a correct CSS transform can worsen biased-noise protection.
- [Expert packet](EXPERT_REVIEW_PACKET.md) remains unsent. Independent proof
  review, priority assessment, a same-task external solver benchmark, large
  indecomposable performance and practical workflow advantage remain open.

Both mission gates are false. Intake of unrelated public workflow data does
not alter the theorem or constitute a scientific admission.
