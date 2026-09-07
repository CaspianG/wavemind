# R8 evidence package — prepared locally, not sent

Updated 2026-09-07 by gap-auditing the existing packet at `0d7b274`, not by
creating another packet. Purpose: critical correctness/prior-art review,
not endorsement. No external reviewer has received it. This is not a max
review packet; no max/xhigh invocation is authorized or performed.

**Current verdict:** recognition novelty is not admitted. The superseding
[theorem audit](PRIOR_ART_THEOREM_AUDIT.md), committed at `1558f08`, supplies
an ordinary-finite-algebra reduction that the older draft did not confront.
Its correctness and status as a standard consequence need independent review.
The frozen proof/results retain their historical pre-audit wording and hashes;
read this packet and [current brief](R8_NEXT_GATE_BRIEF.md) for the verdict.

## Gap audit: reuse, do not duplicate

| Requested element | Existing material | Gap closed in this packet |
|---|---|---|
| Minimal falsifiable claim | SCIENTIFIC_DECISION_GATE.md, steps 1–7 | Separate the atom lemma, recognition consequence and novelty claim. |
| Step-by-step prior-art dependency | PRIOR_ART_THEOREM_AUDIT.md; LC_SCALAR_COMPONENTS.md | Map every proof step and expose the newer algebra reduction. |
| Reproduction and expected evidence | README.md; two results/receipt pairs | Consolidate commands, source pins, hashes and expected summaries. |
| Strong negative tests | Existing preflight and tamper tests | Identify exact counterexamples, test names and what each does not refute. |
| Independent review question | Older packet's four broad questions | Replace with one reduction question and an explicit novelty-kill rule. |

## 1. Minimal exact claim and its falsifier

Let S <= F2^(2n), with n >= 1, be specified by L binary row generators. Let
E be its **full** unital algebra of site-local 2x2 maps preserving S, and B
the scalar masks in E. For an atom C of B, let E_C be the restricted preserving
algebra and choose any site i in C.

**Core lemma:** for every T in E_C with trace(T_j)=1 at every site, if T_i
has rank one, every T_j is a rank-one idempotent. A single such T with a
different determinant elsewhere on the same atom would refute it. Closure,
the atom restriction and all-site trace constraints are essential.

**Recognition consequence:** some independent single-qubit Clifford tuple
maps an isotropic S (any rank 0 through n) to some CSS space iff, on every
atom, at least one of the six systems fixing a rank-one anchor block is
consistent. The procedure supplies an invertible local tuple or six XOR
inconsistency certificates on a failing atom, with a claimed deterministic
O(L n^2+n^4) F2-operation bound. An admitted input with a wrong answer, invalid
witness/certificate, or a failed stated complexity bound refutes the respective
claim. Detailed equations and row-action convention: frozen
[proof steps 1–7](SCIENTIFIC_DECISION_GATE.md).

Redundant generators, unused sites and the zero space are included. The
algebraic lemma also covers non-isotropic spaces, but those are not physical
stabilizer codes. No target code, ancilla, entangling operation, noise benefit
or measured runtime superiority is part of the claim. Finite agreement does
not prove it, and correctness does not establish novelty.

## 2. Dependencies and the still-unclosed novelty gap

The step numbers match the frozen proof. Elementary identities below are
proved there, not attributed to an invented external theorem number.

| Step | Dependency and exact source | What is known / what remains local |
|---|---|---|
| 1: construct E | Ordinary annihilator equations g T w^t=0; frozen proof step 1 | Elementary linear algebra; completeness uses ordinary, not symplectic, annihilators. No novel algebra construction claimed. |
| 2: scalar atoms | Mirandola–Zémor [§2.3, Lemma 2.7 and proof](https://arxiv.org/html/1501.06419v2) | Disjoint projector basis of a subalgebra of K^n is known. |
| 3: independent supports | Same source, Lemma 2.10 | Code decomposition is known under its full-support hypothesis; paired coordinates, zero-extension of masks and unused sites are handled explicitly in our steps 2–3, not silently assumed from that lemma. |
| 4: determinant constant on an atom | 2x2 Cayley–Hamilton: T_j^2+T_j=det(T_j)I; frozen step 4 | The identity is elementary; scalar-algebra closure and step 2 imply the atom consequence. The application is a local deduction, not a located novel theorem. |
| 5: six anchor systems and negative certificates | Six trace-one, determinant-zero binary matrices; elimination, frozen step 5 | Counting and XOR contradiction certificates are elementary. Their recognition use is the candidate consequence to review. |
| 6: projector iff CSS; local Clifford witness | Albert, [Appendix F.2, proof of Lemma F.2, equations 186–189](https://arxiv.org/html/2608.05688v1); frozen step 6 | CSS invariance under the X projector and conjugated projectors are known. Our row convention uses P G=G D and proves both directions for an unknown target; the cited lemma itself assumes two CSS spaces. |
| 7: arithmetic complexity | Frozen step 7, c-site systems with O(c^2) equations in 4c variables, sum c^4<=n^4 | Local cost accounting for ordinary elimination; not a published SOTA comparison or a runtime measurement. |

**The strongest competing route is already written, not merely suggested.**
[Brooksbank–Wilson, §2.2, Theorem 2.5 / Remark 2.1, manuscript pp. 6–7](https://www.researchgate.net/publication/228776809_Computing_isometry_groups_of_Hermitian_maps)
provides radical/semisimple structure and effective images/preimages; the
theorem is Las Vegas and the remark describes a characteristic-dependent
deterministic variant. This ordinary-algebra interface must not be confused
with their odd-characteristic isometry results. The original Rónyai 1990
full text remains unobtained; no theorem number or exact O(n^4) bound is
attributed to it.

The [superseding audit, §1, reduction steps 1–7 and complexity subsection](PRIOR_ART_THEOREM_AUDIT.md)
derives, rather than quotes: faithful two-dimensional modules imply J^2=0;
visible simple factors are F2, F4 or M2(F2); F4 rejects, M2 selects a primitive
idempotent, and shared F2 characters impose x_a XOR x_b=1. A quotient preimage
a lifts by e=a^2, preserving physical ranks. Its direct small-module variant
claims the same arithmetic bound without six anchors. Independent checking
must cover the radical kernel, simultaneous simple-action surjectivity,
characteristic-2 lift and complexity. This alternative is **not implemented
or independently reviewed**, and its exact CSS corollary has not been located
in an earlier publication. These are open review/provenance gaps, not evidence
of R8 priority. Exact six-certificate formatting alone is no established new
scientific capability.

Other comparisons remain bounded: Ivanyos–Qiao Proposition 32 needs a selected
right ideal; Fact 33 compares ranks, not chooses them. Fixed-target graph-LC
algorithms do not directly supply the arbitrary-rank/unknown-target reduction.
Exact source locations, characteristic restrictions and proof-line caveat are
in [audit §§2–3](PRIOR_ART_THEOREM_AUDIT.md); those papers are not refuted.

## 3. Reproduce the evidence, not the verdict string

From the research repository root with Git history present. Historical runtime:
Python 3.13.2, NumPy 2.5.2; pytest is needed for regression tests. The current
checkout retains frozen computational sources. These commands are read-only
replays of saved evidence, not new experimental runs:

```sh
python research/breakthrough/verify_r8.py
python research/breakthrough/decision_gate_falsifier.py --verify research/breakthrough/runs/decision_gate
python research/breakthrough/verify_prior_art_applicability.py
python -m pytest -q research/breakthrough/test_lc_r8.py research/breakthrough/test_r8_evidence.py research/breakthrough/test_decision_gate.py research/breakthrough/test_prior_art_applicability.py
```

| Replay | Frozen source SHA | Expected result |
|---|---|---|
| R8 | `fff2c991506344b7f69be6c4357bd52c1f91eb8b` | `R8_frozen_evidence_verified`; 2,897 small subspaces, 612,642 local assignments, 96 reused R7 inputs; 2,681 positive / 216 negative small cases. All 549 isotropic small cases are positive. |
| Follow-up gate | `0692b111e141e4546a99c29a63359c2b935d46f4` | `full_read_only_replay_pass`; 29,228 unital spaces, 519 algebras, 223 algebra negatives; 10 complete graph orbits, 5 physical negatives, zero unresolved. |
| Prior-art controls | `2459ecb902ede227e6ee15304e0416f6dafb2ed7` | `prior_art_applicability_evidence_verified`; 2 source examples, 2,592 assignments; arbitrary-idempotent shortcut refuted. |
| Targeted pytest | Current checkout; underlying frozen files pinned by receipts | 16 passed, 0 failed; deliberate corruption must be rejected, not accepted as another pass. |

Expected SHA-256 of preserved files:

| File under research/breakthrough | SHA-256 |
|---|---|
| runs/r8/inputs.jsonl | `4a3ee414420192e67163f6a9c25dbc0769a60e81398dc5a04d2363bcb8d87027` |
| runs/r8/raw.jsonl | `8ce2370274908cdb0fb61266f31ec9330dd3bfcce7307fc04c7eb345db6f03b5` |
| runs/decision_gate/raw.jsonl | `83bad867a3e74c7540a48d583929c30f23db45aadb30c7d9c012edb3cc554c52` |

The verifiers check receipt-listed source bytes against Git, regenerate inputs
and exact answers, check certificates and summaries, and check these hashes.
Receipts/results: [R8](runs/r8/result.json),
[follow-up](runs/decision_gate/result.json),
[source controls](runs/prior_art_applicability/result.json).
Run elapsed times and receipt timestamps are not reproducible hash targets.

For an optional fresh reproduction, create a separate clean checkout at the
matching source SHA; do not reset this workspace or overwrite preserved runs.
In the R8 checkout use `python research/breakthrough/experiment_r8.py --output NEW_R8_DIRECTORY`;
in the follow-up checkout use `python research/breakthrough/decision_gate_falsifier.py --output NEW_GATE_DIRECTORY`.
Both directories must not exist. These commands are instructions for review,
not runs performed by this package update. Exact finite results should match;
resource-limited results must stay unresolved, never be relabelled negative.

## 4. Best counterexamples and negative tests

| Control / exact test | Expected observation | What it refutes or protects |
|---|---|---|
| Two Bell pairs: XXII, ZZII, IIXX, IIZZ; `test_undecomposed_one_anchor_is_insufficient` | Preserving trace-one blocks diag(1,0) on the first pair and [[0,1],[1,1]] on the second have ranks 1,1,2,2. | Dropping the atom restriction is false, not the actual R8 lemma. |
| `test_ablation_controls` in test_decision_gate.py | Both `without_closure_implication_fails` and `without_atom_restriction_implication_fails` are true. | Algebra closure and atom restriction cannot be removed. Exact matrices are in the existing `ablations()` record. |
| Five-qubit generators XZZXI, IXZZX, XIXZZ, ZXIXZ; `test_known_four_and_five_qubit_controls` | Negative; exact 6^5 frames, R8, R6 and dense certificates agree. XXXX/ZZZZ is the paired positive control. | A genuine isotropic proper-code negative, unlike the 216 non-isotropic R8 small negatives. |
| Seven-site `cycle` (C7), `hash-0`, `hash-1`, `hash-6` in follow-up raw data | Full graph LC orbits negative; each has one size-seven scalar component. | Physical indecomposable negative coverage; not a large-instance benchmark. `hash-4` is also negative but decomposes 6+1. |
| F4={0,I,F,I+F}, F=[[0,1],[1,1]]; prior-art replay | Only idempotents 0 and I, ranks 0 and 2. | A generic nonzero idempotent is insufficient. Does not refute the new quotient-rank-selection reduction or a cited algebra theorem. |
| `test_dense_checker_rejects_corrupted_witnesses` | Reject missing partition site, modified projector and empty contradiction. | Certificate acceptance must depend on equations, not the claimed answer. |
| `test_r8_verifier_rejects_tampered_evidence`; `test_changed_result_count_is_rejected` | Reject changed raw bytes and counts in temporary copies. | Frozen provenance and result integrity. Original runs remain untouched. |
| `test_small_graph_orbit_and_resource_limit` | A one-state cap returns unresolved. | Resource exhaustion is not a mathematical negative. |

No counterexample to the stated R8 theorem was found in these finite domains.
The alternative known-algebra route is the strongest **novelty** falsifier;
it is a written proof obligation, not something these tests have verified.
All local checkers share an investigator/project and some helpers: they are
not independent investigator replications or executed external SOTA solvers.

## 5. One question to the independent reviewer

**Does the explicit ordinary-algebra reduction in audit §1 establish the same
arbitrary-rank, unknown-target, F2 recognition/witness task as R8 as a standard
consequence of existing finite-algebra methods, including correlated physical
ranks, the square-zero lift and the claimed deterministic cost; if not, which
first precise implication fails (with a counterexample or missing hypothesis)?**

**Novelty-kill criterion, recorded before receiving review:** if an independent
review supplies an exact published same-task result, or validates this (or
another explicit) reduction as a standard consequence of identified prior
results without an essential new recognition lemma, mark the polynomial
recognition contribution `not_new_recognition_consequence`. A generic algorithm
name, an arbitrary idempotent, a supplied-pair oracle or passing tests does not
meet that criterion. If only an unspecified polynomial bound is established,
the exact exponent/certificate distinction needs separate substantive review;
it does not automatically rescue the broad novelty claim. Rejecting the
reduction likewise does not establish R8 priority or correctness.

No review response or acceptance is present. Current status stays
`novelty_not_admitted`; no max packet, external send or new benchmark follows.
Fixed-noise benefits remain independently unsupported by
[the workflow boundary control](WORKFLOW_BRIDGE_AUDIT.md). Both mission gates
remain false; the unrelated actual-human terms hold is unchanged.

## Local package validation, 2026-09-07

All three replay commands above completed with their expected statuses,
counts and hashes. The targeted pytest command passed **16 tests, 0 failures,
in 13.62 seconds**. This is a recheck of existing evidence, not additional
scientific cases or an independent reproduction. Only this existing packet
and mission_status.json were changed; frozen proofs, code, receipts, raw
results and the terms hold were preserved.

## Sharing boundary

If approved, share only the agreed proof, source, public-source examples and
synthetic/QEC audit material. Do not include private account data, credentials,
the broader workspace, protected LongMemEval contents or unrelated product
history. A live public link must be verified before it is inserted into a sent
request; local file links above are for preparation and are not public URLs.
