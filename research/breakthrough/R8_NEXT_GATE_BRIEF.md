# R8: handoff for the next scientific gate

Read this page first. Do not rerun the entire investigation to recover scope.
This is a local proof candidate, not novelty clearance. No new max-effort gate
or external reviewer interaction is authorized by the current intake task.

## Exact remaining claim

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

The minimal residue is the **recognition consequence**, not new scalar
decomposition, Cayley–Hamilton, conjugated projectors or a noise guarantee.
Detailed proof: [SCIENTIFIC_DECISION_GATE.md](SCIENTIFIC_DECISION_GATE.md).

## Outstanding prior-art questions, not findings of absence

1. [Mirandola–Zémor, §2.3 Lemmas 2.7/2.10](https://arxiv.org/pdf/1501.06419v2):
   scalar/code decomposition is already known and explicitly excluded.
2. [Rónyai, finite-algebra structure algorithms](https://www.sciencedirect.com/science/article/pii/S074771710880017X):
   only the abstract was audited. Does an exact general reduction already
   supply the prescribed rank-one block idempotent in characteristic two?
3. [Ivanyos–Qiao, §4.2–4.4](https://arxiv.org/pdf/1708.03495v3):
   Proposition 32 and Fact 33 remain relevant even though main isometry
   results have a characteristic restriction. Need exact reduction or a
   precise mismatch. The F4 shortcut counterexample does not refute this paper.
4. [Van den Nest–Dehaene–De Moor / Bouchet](https://arxiv.org/pdf/quant-ph/0405023)
   and [Claudet–Perdrix §3.1](https://drops.dagstuhl.de/storage/00lipics/lipics-vol334-icalp2025/html/LIPIcs.ICALP.2025.59/LIPIcs.ICALP.2025.59.html):
   supplied-pair graph equivalence is not yet a reduction for arbitrary rank
   and an unspecified CSS target. Investigate that reduction, not just titles.
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
