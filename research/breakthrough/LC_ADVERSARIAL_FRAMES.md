# R7: adversarial affine frames for the positive stitching branch

Registered purpose: exercise the branch that R6's main corpus did not use.
This is a constructed mechanism falsifier, not external task data, a novel
code family, a runtime speedup measurement or a new scientific admission.
R5/R6 inputs, implementations and evidence stay frozen.

## Nontrivial code and complete algebra

Take B disjoint blocks of even length L. On each block use stabilizers
X^L and Z^L. They commute because L is even and are independent for L>=2.
The tensor product has n=LB and stabilizer rank 2B. L=2 gives Bell pairs;
L=4,6 give codes with unencoded logical degrees of freedom. These are known
elementary CSS constructions, not newly discovered codes.

Every site-local linear map preserving this stabilizer space must be the
same 2x2 map on each site within a block: applying it to X^L and Z^L must
again give uniform X/Z combinations on that block. Conversely every such
blockwise-uniform map preserves the code. Thus the complete local preserving
algebra is E = product_b M2(F2), dimension 4B.

Arbitrary per-qubit Clifford frame changes C, qubit permutations and invertible
generator mixing hide this presentation without changing it. Transform maps
as C^(-1) T C when transforming stabilizer rows as S C. The checker verifies
the matrix-unit multiplication table of E, its dimension, preservation of S,
and the dimension of its trace-one slice. A separate dense annihilator and
full 4n-variable preservation system check that E is the complete preserving
algebra, not merely a closed subalgebra of the expected size. No claim relies just on the name
of the construction or on a positive output from the search solver.

## Guaranteed hard affine representation

In each block set T0=[[0,1],[1,1]], an order-three map. Its trace is one,
but its determinant is one, so it is not a rank-one projector anywhere.
Use trace-zero kernel generators I_b, E12_b, E21_b, independently per block.
They span the complete translation space of the trace-one slice, dimension 3B.

For this localized basis, each of T0+V_j is either bad everywhere or good
only on the single block supporting V_j. When B>=2 no member of this d+1
candidate list is globally good. The R6 cover construction must therefore
use exactly B nonempty, disjoint pieces to produce a positive answer. This
requirement is derived before the experiment, not selected from its output.

Additional arms mix the kernel basis by invertible row operations and/or
shift T0 within the same affine slice. These arms test representation changes;
some can legitimately have a globally good single candidate. The hard arm's
coverage requirement does not silently extend to them.

## Independent checks and two ablations

The frozen R6 helper operates on packed a,b,c bit blocks. The R7 checker uses
explicit dense 2x2 matrix products per site. For every candidate T it checks
preservation, trace, G=I+T^2+T, membership in E, and the scalar-mask property.
For every accepted piece it checks the remaining mask R, selected mask M,
M T, accumulated P, disjointness, membership in E and preservation of S.
At completion, P must have trace one, determinant zero and P^2=P at all
sites, agree with the packed helper, and yield a CSS group under explicit
local gates verified by the separate dense rank checker.

Ablation 1 keeps only a single candidate from the same d+1 list. It must fail
in every hard-arm case, although a CSS frame exists. Ablation 2 adds all
G(T)T without partitioning overlapping masks. Its output remains in E but
need not have rank-one blocks; record failures instead of treating an
unpartitioned sum as a valid projector.

Assumption control: an arbitrary affine slice need not be part of a closed
algebra. On two sites take T0=(P,F), D=(H,H), with P=diag(0,1),
F=[[0,1],[1,1]], H=[[0,1],[1,0]]. The span of I,T0,D is not multiplicatively
closed. Its trace-one slice has four points, each good at just one site;
stitching can produce a map outside that span. Verify and report this
counterexample to any version of the claim that omits algebra closure.

## Boundaries and next scientific questions

This experiment addresses representation sensitivity and the exact branch
coverage gap from R6. It cannot establish novelty or useful performance in
real consumer/enterprise workflows. Projection conjugation and polynomial
LC equivalence algorithms have known predecessors documented in
[the R6 proof](LC_STITCHING.md). External comparison and expert scrutiny
remain mandatory. The scientific and mass-indispensability gates stay false.
