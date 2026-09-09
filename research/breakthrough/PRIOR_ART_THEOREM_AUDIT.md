# Theorem-level applicability audit after R7

## Superseding R8 pressure-point audit — 2026-09-07

**Decision: do not prepare or run a new max-review packet.** Polynomial
recognition does not presently survive as a stand-alone novelty claim: the
rank-selection gap can be closed by the explicit finite-algebra reduction
below. This is a paper derivation in this audit, not a located prior publication
of the CSS corollary, independent proof review, or executed external baseline.
The original R8 proof/results are not refuted or rewritten. Its six-anchor
presentation and certificate format can remain useful without establishing a
new scientific capability. The older verdict below is historical.

### 1. Rónyai: exact rank-selection reduction, with a source-access limit

The full 1990 Rónyai paper was not obtained: publisher requests failed and
targeted author/repository searches did not supply its theorem text. **Do not
upgrade its abstract-only entry to a full-paper review or invent a theorem
number.** Instead, the concrete published algorithmic interface was read in
[Brooksbank–Wilson, author-uploaded text, §2.2, Theorem 2.5 and Remark 2.1](https://www.researchgate.net/publication/228776809_Computing_isometry_groups_of_Hermitian_maps),
manuscript pp. 6–7. It supplies the radical, a semisimple complement and an
explicit quotient into matrix algebras over finite fields, including effective
images/preimages. Theorem 2.5 is Las Vegas; Remark 2.1 attributes a deterministic
variant polynomial in the characteristic and input parameters to Rónyai.
At fixed characteristic 2 that parameter is constant. These ordinary-algebra
statements do not require an involution or odd characteristic; the distinct
Taft/isometry results do. Do not attribute their stronger, odd-characteristic
conclusions to this interface.

#### Reduction derived here (not quoted from those papers)

Let A=E <= product_i M2(F2) be the full unital preserving algebra and
V_i=F2^2 its supplied physical modules. Put J=Rad(A). Use ordinary associative
algebra structure, not a *-algebra assumption. The following supplies the
prescribed ranks; merely requesting a nonzero idempotent does not.

1. Each V_i has either one simple constituent of binary dimension 2 or two
   of dimension 1. The direct sum of the V_i is faithful. The kernel K of
   the action on all their composition factors is nilpotent: in a basis
   adapted to a local flag its matrices are strictly triangular, and K^2=0.
   Conversely J annihilates every simple constituent, so J<=K. Since any
   nilpotent ideal is contained in J, K=J and **J^2=0**. Thus all simple
   factors of A/J are visible on these physical composition factors.
2. Write A/J as a product of M_d(F_(2^f)). A simple module for such a factor
   has binary dimension d*f. Visibility and the two-dimensional bound leave
   only F2, F4 and M2(F2). This is a statement about simple factors of A/J,
   not a claim that the original physical blocks are independent.
3. A two-dimensional irreducible physical module of F4 type forces failure:
   idempotents in the field are 0 and 1, acting with ranks 0 and 2. This
   recovers the previous F4 control as a correct negative branch.
   For each M2(F2) factor choose one primitive idempotent diag(1,0); it has
   physical rank 1 on every equivalent copy of its natural simple module.
4. Give each F2 simple factor one binary variable x_a. A physical block with
   one-dimensional factors a,b requires the *integer* rank x_a+x_b=1.
   For binary variables this is exactly x_a XOR x_b=1. A repeated factor
   gives a contradictory self-loop. Otherwise solve the resulting graph
   two-colouring / binary linear system. An odd cycle is a negative
   certificate. These shared variables account for correlated rank choices;
   independently choosing each site's projector would be wrong.
5. These choices define an idempotent q in the full semisimple quotient.
   Take any preimage a in A under the explicit quotient map. Then
   a^2+a belongs to J. Since J^2=0 and powers of a commute,
   (a^2+a)^2=a^4+a^2=0. Therefore **e=a^2 is an idempotent** in A lifting q.
   This formula uses characteristic 2 and no division by 2 or field extension.
6. The physical rank is preserved by the lift: on a reducible V_i an
   idempotent is triangular with diagonal x_a,x_b, hence rank 1; on an
   irreducible V_i the radical acts as zero and the selected primitive
   matrix has rank 1. Equivalently the rank of an idempotent adds over an
   invariant composition series. Do not use characteristic-2 trace alone
   to equate rank 0 with rank 2.
7. Diagonalize each e_i over F2 and use the already-known projector/CSS
   bridge. Conversely any requested physical projector induces exactly
   these allowed quotient ranks, so each rejection above is necessary.
   No second CSS code, maximal-rank completion, ancilla, qubit permutation
   or entangling operation has entered the reduction.

This is a complete decision/witness reduction to an ordinary finite-algebra
structure interface over F2. The reading of the original Rónyai theorem is
still incomplete, but **the general-algebra route cannot be dismissed for
lack of rank selection or characteristic-2 lifting anymore**.

#### Complexity boundary: not just a randomized black-box comparison

The exact O(L n^2+n^4) bound is not extracted from Rónyai's unavailable text
or inferred from Remark 2.1's unspecified polynomial. There is also a direct
small-module specialization of the reduction above, derived here:

- First construct a basis of A, dimension m<=4n, by the same preservation
  equations as R8, costing O(L n^2+n^4). Do not include unverified algebra
  closure of an arbitrary linear space as an extra promised input.
- Test the three possible invariant lines in each V_i on this basis. A
  reducible block yields two characters in F2^m. If none is invariant, its
  image algebra is irreducible: its commutant is either F2 or F4. Finite
  density/Artin–Wedderburn then gives M2(F2) or F4 respectively. These
  constant-dimensional linear computations cost O(n*m).
- Identify equal one-dimensional characters. Identify equivalent
  two-dimensional simple modules by solving intertwining equations in four
  variables for each pair of blocks. A nonzero intertwiner of irreducibles
  is invertible. This costs O(n^2*m); no exponential module search is needed.
- Select quotient ranks as above, transport each selected 2x2 matrix through
  the intertwiners, and impose its action on one representative of every
  simple module, plus the character values. These are O(n) linear equations
  in m unknown coefficients of a. The simultaneous action map is onto the
  product of simple factors: distinct simple-module kernels are distinct
  maximal two-sided ideals, so the Chinese remainder theorem applies.
  Therefore compatible selected values have a preimage. Solve in O(n^3),
  then square a once and diagonalize the physical blocks.

The resulting paper bound is again O(L n^2+n^4), deterministic, without the
scalar-atom/six-anchor lemma. It needs independent scrutiny and has **not**
been implemented or benchmarked here. This does not show that Rónyai published
this exact specialization. It does show why matching the exponent alone is
not a defensible novelty-survival decision for max. The six specific R8
inconsistency certificates are not produced by this alternative; that output
format remains an expository/implementation distinction, not an established
complexity separation or new physical capability.

### 2. Ivanyos–Qiao: useful construction after selection, not selection itself

Read [v3, Fact 11 and its proof; §4.2 Proposition 32 / Fact 33 and proofs;
§4.3 Lemma 35](https://arxiv.org/html/1708.03495v3) (PDF pp. 11–12, 28–30),
and the characteristic convention in §1. Proposition 32 starts from a
**supplied non-nilpotent right ideal** and returns an idempotent whose quotient
is a left identity of that ideal modulo the radical. Fact 33 compares already
given idempotents with matching simple-component ranks. It does not choose
a desired physical rank vector. The main small-field route still uses
Lemma 35, which explicitly excludes characteristic 2.

Exact use in our reduction: after selecting q above, set
I=pi^(-1)(q(A/J)). The ideal is not nilpotent. An output e in I with the
Proposition-32 property generates the same quotient right ideal as q, hence
has the same ranks on every simple type. The composition-series argument
above then gives physical rank 1. Without q (or equivalent rank selection),
calling the proposition with I=A merely permits e=1, which is rank 2 at
every site. Fact 33 is classification of these modules, not the missing
search oracle. Thus the proposition can complete the route, but is not a
stand-alone CSS recognizer.

Characteristic-2 justification is supplied here, not attributed to the paper's
global convention: Fact 11's nilpotence/Fitting construction needs no division
by 2. For orthogonal-on-one-side idempotents e,f with ef=0, the valid growth
step is g=e+f-fe; g^2=g, ge=e, gf=f and gA=eA direct-sum fA. This works in
characteristic 2 as well. The extracted PDF and arXiv HTML proof instead show
an e+fe growth step. That step alone does not establish growth: with
e=[[1,0],[0,0]] and f=[[0,0],[1,1]], ef=0 but e+fe has the same matrix rank
as e. We record this local proof-line issue, **not a refutation of the
proposition**; the displayed g repairs the needed elementary step. Our
square-zero-radical lift avoids relying on it altogether. No author contacted.

### 3. Bouchet / Van den Nest / Claudet–Perdrix: precise pairwise mismatch

Read [Van den Nest–Dehaene–De Moor, full three-page note, especially
equations (2)–(5) and Lemma 1](https://arxiv.org/pdf/quant-ph/0405023).
The supplied matrices represent rank-n self-dual stabilizer spaces. Two fixed
graph adjacencies make the intertwining condition linear; local invertibility
adds determinant-one constraints. The O(n^4) procedure and its small candidate
set are credited to Bouchet. Bouchet's original 1991 proof was not separately
retrieved here; the note states its lemma but refers that proof to Bouchet.

Read [Claudet–Perdrix §3.1, Proposition 7, Lemma 8, Remark 9,
Proposition 10 and proofs](https://drops.dagstuhl.de/storage/00lipics/lipics-vol334-icalp2025/html/LIPIcs.ICALP.2025.59/LIPIcs.ICALP.2025.59.html).
The added constraints are linear in the local transformation variables for
two *fixed* graphs. Proposition 10 assumes connected graphs with an even-degree
vertex; Remark 9 does not give the fully constrained Class-alpha case.

The following are our task-level deductions, not claims from those papers:

- **Unknown target:** the fixed-coefficient equation
  Gamma B Gamma' + Gamma A + D Gamma' + C=0 becomes a joint nonlinear
  search if Gamma' is also unknown. Asking for an arbitrary bipartite graph
  in an LC orbit is not the same input as giving that graph. A supplied-pair
  oracle does not itself provide a polynomial-size complete target list.
- **Arbitrary rank:** the note's elimination of the basis-change matrix
  uses self-duality. For rank r<n, symplectic orthogonality gives containment
  in a (2n-r)-dimensional complement, not equality with the r-dimensional
  target. For example, spans of X1 and X2 on two qubits are orthogonal but
  unequal. Completing to a stabilizer state introduces a choice of logical
  stabilizers. A CSS completion's projector need not preserve the specified
  subcode; that preservation condition cannot be dropped.
- **Singular witness:** our P_i has determinant zero, whereas the pairwise
  local Q_i has determinant one. Replacing one constraint by the other is
  not authorized by their lemmas. Writing P=Q D Q^(-1) is possible, but
  introduces a conjugation constraint; it is not one of the permitted extra
  linear constraints without another proved reduction.

Accordingly these cited pairwise algorithms do **not directly** settle the
stated arbitrary-rank, unknown-target problem. This is a precise mismatch,
not a proof that no future gadget or alternate reduction can exist. The
finite-algebra reduction in question 1 already supplies the stronger pressure
against the novelty claim; we do not need to invent a pairwise reduction.

### Gate outcome and evidence limits

No new scientific novelty admission, max invocation, max-review packet,
external solver execution, R8 rerun, model score, paid call or product change.
Only targeted theorem reading and the deductions above were performed.
PDF page screenshots for Ivanyos–Qiao failed in the reader; the relevant
formulas/proof were cross-checked against the versioned arXiv HTML. Do not
claim complete visual PDF verification. Rónyai's full original text remains
an explicitly bounded source gap, not evidence of absence.

The next justified scientific action is independent scrutiny of this
rank-selection/lifting reduction, particularly the faithful-module radical
kernel and simultaneous simple-action surjectivity. Until it fails or a
separate substantive contribution is established, do not spend max on the
old claim that polynomial CSS recognition itself is a new capability.

---

## Historical R7 applicability audit (preserved)

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
