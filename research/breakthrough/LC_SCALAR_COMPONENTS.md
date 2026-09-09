# R8: scalar-support decomposition and a six-anchor alternative

Derived before R8 main generation, 2026-09-07. This is an internal structural
comparator to R6, not an executed external package or cleared novelty.
R5, R6 and R7 remain unchanged.

## Known foundation and the remaining question

[Mirandola and Zemor, arXiv:1501.06419v2](https://arxiv.org/pdf/1501.06419v2),
section 2.3, Lemma 2.7, gives a disjoint-projector basis for any subalgebra
of K^n. Their Lemma 2.10 relates stabilizer projectors to the direct-sum
decomposition of a full-support linear code. Thus neither scalar-mask algebra
nor decomposition by its disjoint projectors is a new discovery here.
The entire relevant section was read as extracted PDF text; visual page
retrieval failed. No claim is made about uninspected sections.

For our paired-coordinate problem the following is a derived specialization,
not a quotation of a theorem about local-Clifford recognition from that paper.
Its six-anchor consequence still requires independent theorem/prior-art review.

## 1. Compute the actual independent supports

Let S be any binary linear subspace of F2^(2n), with row coordinates (x,z).
Let E be its full preserving algebra of site-local 2x2 linear maps. Define

```
B = {m in F2^n : diag(m_i I_2) preserves S}.
```

B is a unital subalgebra of F2^n with coordinatewise multiplication. Its
complete linear constraints, for generators g=(x,z) and an ordinary
annihilator basis w=(u,v), are m dot ((x & u) xor (z & v)) = 0.

From any basis of B, put two coordinates in the same component precisely
when their columns of basis values agree. For each occurring signature s,
the product of basis masks with s_j=1 and their complements with s_j=0
is the indicator of that component. It belongs to B. These indicators are
disjoint, sum to 1, and span B; their number equals dim B. Zero support in S
causes no exception: each unused site is a singleton component.

For an indicator e, eS is supported inside that component and belongs to S.
Consequently S is the direct sum of these projected subspaces. The full
site-local preserving algebra is correspondingly the product of the component
preserving algebras. Every component's scalar algebra is exactly {0,1}:
any finer scalar mask there would extend by zero to split the original atom.

## 2. Six linear systems per component suffice

Fix a component C and one anchor i in C. Let T preserve S_C and have trace
one at every site of C. Cayley-Hamilton in dimension two gives

```
G(T) = I + T^2 + T = diag((1 + det T_j) I_2).
```

G(T) is a scalar map in the preserving algebra. Because the component is an
atom, G(T) is either zero everywhere or identity everywhere. Therefore, if
T_i is a rank-one idempotent at the anchor, every T_j on C is rank-one.

There are exactly six rank-one idempotents in M2(F2): trace one and determinant
zero. For each of the six, solve the *linear* constraints of preservation,
trace one on C, and that fixed anchor block. A consistent system gives a
projector on all of C; if all six are inconsistent, no desired projector
exists on C. Assemble the projectors on the disjoint components. Diagonalizing
their local blocks gives the CSS split, by the frozen R5 criterion.

This works for arbitrary linear S. Non-isotropic S is not a physical
stabilizer code; its CSS split is only a linear-algebra statement. For an
isotropic S it answers the same local-Clifford-to-CSS question as R6.

## 3. Algorithmic and novelty implications

After reducing redundant generators, scalar constraints have at most O(n^2)
rows and n variables. Each component has at most O(|C|^2) preserving equations
in 4|C| variables, plus trace and four anchor constraints. At most six ordinary
Gaussian eliminations per component give O(n^4) field operations overall,
since sum |C|^4 <= n^4. Reading/reducing an input of L generators adds
O(L n^2). This is an asymptotic arithmetic bound, not a measured speedup.

R6's good masks are elements of B, so its multi-piece assembly never stitches
across an indecomposable support. It selects solutions on pre-existing direct
summands. R7's hard affine frames may therefore be representation hardness,
not hard coupled instances of the original recognition problem.

If verified, this is a simpler *internal* same-task algorithm. Do not call it
an externally executed state-of-the-art baseline or infer a novelty verdict
from its equivalence to R6. The new candidate question narrows to the
recognition consequence and its proof, not invention of code decomposition.

## R8 falsifier

See protocol_r8.json. Exhaust all 2,897 linear subspaces for n=1,2,3, including
non-isotropic ones; compare every result with all 6^n invertible local maps.
Use independent dense reconstruction of scalar and anchor constraints, direct
finite-span CSS membership, and unchanged R6 theorem-level reconstruction.
Only the 549 isotropic inputs are passed to R6's public stabilizer solver.
Also replay the 96 already published R7 hard frames using only their code
generators, not their adversarial affine bases. These are reused cases.

No quantum hardware, paid calls, external benchmark execution, consumer or
enterprise validation is provided by this experiment. Both mission gates
remain false regardless of its outcome.
