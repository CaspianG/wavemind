# R6 candidate: remove the residual enumeration by algebraic stitching

Status: derived after R5, before R6 data generation. This is a candidate
theorem and implementation to falsify, not externally reviewed novelty.
R5 and its exponential worst-case implementation remain frozen unchanged.

## Claim

Let E be the algebra of site-local binary 2x2 maps that preserve a linear
subspace S of F2^(2n). Let A be the affine slice in E whose local trace is one
at every site. Write each block as [[a,b],[c,1+a]]. Then a rank-one idempotent
at every site exists in E if and only if:

1. A is nonempty; and
2. there is no site at which b and c are both identically one throughout A.

For stabilizer S, this is equivalent to full local-Clifford-to-CSS existence
by the R5 projector criterion. It is not a statement about general unitaries,
ancilla addition, entangling Clifford circuits, distance or noise performance.

## Proof of the new step

E contains I and is closed under addition and multiplication: preservation
of S is closed under linear combinations and composition, and the site-local
block form is closed under both. No symplectic property of its elements is
assumed. They are linear maps, usually singular, not physical gates.

Choose T0 in A and a homogeneous basis V1,...,Vd for its translation space.
For any T in A, Cayley–Hamilton at each site gives

```text
T_i^2 + T_i = det(T_i) I_2 = b_i c_i I_2.
G(T) = I + T^2 + T.
```

Thus G(T) belongs to E and is the scalar coordinate mask selecting exactly
the sites where T is a rank-one idempotent. This scalar mask is central in
the entire site-local matrix algebra. In particular G(T) T is in E, is a
rank-one idempotent at those sites, and is zero elsewhere.

Consider just T0,T0+V1,...,T0+Vd. If a site is bad for every one of these
maps, T0 has b=c=1 there and every Vj has b=c=0 there. Hence b and c are
identically one throughout A. Conversely, if they are not both fixed to one,
T0 or one of those d single-basis perturbations is good at that site.

If no site is obstructed, those at most d+1 good masks cover all sites.
Partition that cover algebraically: start R=I and P=0. For each candidate T,
set M=R G(T), then P=P+M T and R=R(I+G(T)). All terms remain in E. R and M
are central scalar masks; each new M has support disjoint from earlier ones.
At termination R=0 and every P_i equals exactly one good T_i. Therefore P
is in E and is rank-one idempotent at every site. Diagonalizing its local
blocks yields an explicit local Clifford sending S into CSS form.

If some site has b=c=1 for all of A, all of its trace-one blocks have
determinant one, whereas rank-one blocks have determinant zero. No desired
P exists. This proves necessity and sufficiency.

**The closure of E is essential.** For an arbitrary affine space of local
matrices, separate feasibility at each site does not imply simultaneous
feasibility. The good-mask construction is justified here only because the
affine space is the complete trace-one slice of a subalgebra. An incomplete
constraint set cannot be used to construct a positive witness without the
final independent rank check. Negative proofs still use necessary constraints.

## Algorithm and complexity boundary

Use the same complete linear invariance system as R5: at most r(2n-r)
equations in 3n bits for a rank-r stabilizer. Gaussian elimination either
produces a linear contradiction or T0 and a kernel basis (d <= 3n).
Evaluate the d+1 masks and stitch them. No 2^d enumeration remains.
Ordinary unoptimized bit-by-bit elimination has polynomial bound O(n^4)
field operations after basis construction; packed integer implementation
changes constants, not that claim. At most d+1 candidate maps are considered.
Polynomial does not mean fast on unlimited n; the practical implementation
still reports UNRESOLVED on a wall limit, never a fabricated negative.

A remaining bad site gives two short proofs: a linear combination of valid
invariance equations implies b_i=1, and another implies c_i=1. A verifier
checks the annihilators, generator indices, and the two XOR identities without
trusting kernel dimension or the search procedure. A positive witness is
checked by direct transformed group ranks, as in R5.

## Closest methods and novelty boundary

Projection invariance, conjugation, and endomorphism algebras are already in
[Dasu–Burton](https://arxiv.org/html/2507.10519v1#S3) and
[Albert](https://arxiv.org/html/2608.05688v1#A6.SS2). R6's proposed additional
step is the determinant-mask cover and its use to remove enumeration for
arbitrary input stabilizers. Do not claim invention of those older ideas.

[Van den Nest, Dehaene and De Moor](https://arxiv.org/pdf/quant-ph/0405023)
describe Bouchet's polynomial algorithm for equivalence of two specified
graph states: a linear solution space plus quadratic determinant constraints
can be searched through a polynomial-size subset. That is a serious prior-art
analogue, not a generic exponential baseline. Its stated target is two given
states, while here the target is any CSS frame and rank may be less than n.
No claim that R6 improves or is independent of that theory is cleared yet.

R6 will compare to exact graph-local-complementation orbit enumeration on
small graph states, not pretend that an old restricted 36-pattern scan is
the best general comparator. For larger arbitrary subspaces, an external
strong general package has not been executed. All mission gates remain false
until novelty, independent reproduction and actual workflow usefulness exist.

## Why the graph oracle answers the same question

For a bipartite graph, apply Hadamard at every vertex of one color. Its
graph-state generators become pure X or pure Z. Conversely a CSS stabilizer
state has X-space A and Z-space A-perp. After column permutation and row
reduction, write A=[I|M] and A-perp=[M^T|I]; Hadamards on the second block
give the graph with off-diagonal adjacency blocks M and M^T. Thus a CSS
state is LC-equivalent to a bipartite graph state. Van den Nest et al.'s
graph-local-complementation equivalence then makes complete finite orbit
enumeration an independent decision oracle for our small graph-state family.
This graph theorem and the enumeration are baselines, not claimed innovations.
