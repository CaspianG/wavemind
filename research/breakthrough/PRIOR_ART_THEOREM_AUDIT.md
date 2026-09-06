# Theorem-level applicability audit after R7

Date: 2026-09-06. Verdict: **candidate survives this targeted comparison;
novelty is not cleared**. This is a source-and-assumptions audit, not an
independent expert review, external solver benchmark or product admission.

## Exact question being compared

Input: generators of any binary stabilizer subspace S of F2^(2n), rank r<=n.
Output: decide whether some tuple of single-qubit Clifford transformations
maps S to CSS form, and provide a witness or a checkable negative certificate.
No ancillas, extra qubits, entangling transformations, physical noise change
or prescribed second code are allowed in this question.

R6 reduces it to a rank-one idempotent at every site in the complete local
preserving algebra E. Its proposed extra step is the trace-one slice and
central determinant masks that make per-site feasibility jointly sufficient.
The frozen proof and source are in [LC_STITCHING.md](LC_STITCHING.md),
SHA `90579911ad56ae2ef85e0c6f96c5c86d98cec178`.

## Primary sources: what is actually established

| Source inspected | Established scope | Applicability to this question |
|---|---|---|
| [Quantum XYZ Stabilizer Codes, v1, §III-C definitions 10–12 and §III-D](https://arxiv.org/html/2607.14988v1#S3.SS4) | Distinguishes unchanged CSS, uniform relabeling, and arbitrary local relabeling; describes the complexity of the last recognition question as open to the authors' knowledge. | This is a direct match of the decision question, not evidence that our proposed answer is correct or first. |
| [Claudet–Perdrix, ICALP 2025, §3.1, Lemma 8 and Proposition 10](https://drops.dagstuhl.de/storage/00lipics/lipics-vol334-icalp2025/html/LIPIcs.ICALP.2025.59/LIPIcs.ICALP.2025.59.html) | Extends Bouchet's pairwise graph-equivalence procedure with linear constraints; the displayed proposition assumes connected graphs with an even-degree vertex. | There are two supplied graph states and an invertibility condition. R6 has an unknown CSS target, may have r<n, and seeks singular projectors. No valid reduction to this proposition has been supplied. |
| [Ivanyos–Qiao, v3, abstract and §4.2–4.4](https://arxiv.org/pdf/1708.03495v3) | Main isometry/symmetrization statements exclude characteristic 2. Proposition 32 separately constructs an idempotent-generated projective ideal; Fact 33 compares ranks in semisimple components. | Do not dismiss every intermediate result because of the main theorems' characteristic restriction. But an arbitrary idempotent or module isomorphism is not automatically the prescribed rank-one block witness; a reduction is still needed. |
| [Rónyai, Computing the structure of finite algebras, publisher abstract](https://www.sciencedirect.com/science/article/pii/S074771710880017X) | Polynomial algorithms for radicals and semisimple components; finite-field factorization/Las Vegas methods are relevant. | Only the abstract was inspected, not the full theorem/proof. Generic structure computation is serious prior art, but this abstract does not settle the local-rank selection problem. |

The original [Van den Nest / Bouchet comparison](LC_STITCHING.md) and
[Rains / Dasu–Burton / Albert warnings](NOVELTY_REVIEW.md) remain in force.
The limited search did not identify a published drop-in algorithm for the
exact input/output above. **Not finding one is not proof that none exists.**

## Executed checks of two tempting wrong substitutions

The [applicability protocol](prior_art_applicability_protocol.json) and
[audit source](prior_art_applicability.py) were committed before execution,
at `2459ecb902ede227e6ee15304e0416f6dafb2ed7`. Expected answers were already
visible in the source; this is not held-out evaluation.

First, the two four-qubit source examples in equations 60 and 61 were checked
with all 1296 local assignments each, all six uniform assignments, and frozen
R6 with separate certificate verification. Example 2 has 16 local CSS
assignments but no uniform one; example 3 has none. This agrees with the
paper and demonstrates why a uniform-frame criterion cannot serve as a
complete comparator. It does not add a new code discovery.

Second, consider E=F4 embedded in M2(F2):

```text
F = [[0,1],[1,1]],  E = {0, I, F, I+F}.
F^2 = I+F.  The only idempotents are 0 and I, of ranks 0 and 2.
```

The exact multiplication/addition audit verifies closure and all four
idempotency tests. E has a nonzero idempotent but no rank-one idempotent.
Therefore the attempted implication "a generic algorithm found a nonzero
idempotent, so the desired rank-one witness exists" is false. This refutes
**that attempted reduction**, not Rónyai, Ivanyos–Qiao or generic algebra
methods as a whole. More sophisticated reductions may well settle the task.

[Receipt](runs/prior_art_applicability/receipt_start.json) and
[all outcomes](runs/prior_art_applicability/result.json) are preserved.
The audit took 0.4228 seconds; this is not a comparative speed claim.
No external software package or independent investigator executed these tests.

Read-only replay checks committed source hashes, repeats all 2592 local
assignments and verifies both R6 certificates. A tampered result count is
rejected by a regression test. The full research suite now has **40 passed**
(4.70 seconds in this run), and Ruff passed.

```sh
python research/breakthrough/verify_prior_art_applicability.py
python -m pytest -q research/breakthrough
```

## Decision, not a victory declaration

1. Keep R6 as a candidate theorem. R7 addresses a mechanism branch; the
   source examples address interpretation. Neither provides novelty clearance.
2. Narrow the possible contribution to the local-to-global recognition
   criterion, its explicit complexity and certificates. Projectors, algebra
   invariance, generic polynomial algebra computation and pairwise LC
   equivalence must not be presented as inventions.
3. A serious remaining falsifier is a reduction through decomposition of E
   and idempotent lifting that already yields the required local ranks.
   Spell out its treatment of the radical, characteristic 2, each physical
   two-dimensional representation and correlated rank choices; an algorithm
   name is not a reduction. A direct scalar-support decomposition is another
   useful way to test whether stitching merely repackages a simpler argument.
4. Seek independent theorem/prior-art scrutiny using the
   [prepared review packet](EXPERT_REVIEW_PACKET.md). It has not been sent.

## Consumer and enterprise gate remains separate and unfulfilled

The QEC recognizer produces a mathematical classification. We have not
demonstrated that this classification improves an independently defined
consumer workflow or an enterprise workflow, let alone by >=10x at preserved
quality, safety and unit economics. There are no participating users, physical
measurements, external reproductions or accepted workflow outcomes here.
The prior device/API diagnostic proposals have not been connected to this
mechanism. Adding more synthetic QEC passes cannot close that gap.

Do not ship this research as proof of a faster or indispensable WaveMind
product. Both original gates stay false; the full mission remains active.
