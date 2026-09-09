# R5: local projector criterion for CSS equivalence

Status before catalog execution: **candidate algebraic audit, no novelty clearance**.
This is a separate QEC research direction after R1–R4 failed to establish a
new mechanism. No WaveMind runtime behavior or product gate changes here.

## Precise question and primary-source gap

[Evolutionary Discovery of Bivariate Bicycle Codes, Appendix F](https://arxiv.org/html/2606.02418v1#A6)
reports 11 CSS-equivalent codes among 368 PBB codes under its tested families.
For the remaining 357, arbitrary mixtures of local Clifford operations remain
outside the published tests. The authors explicitly limit their negative
classification to the covered families. Code search itself is not new.

[Cross and Vandeth, section 7.2](https://arxiv.org/html/2501.17447v1#S7.SS2)
give the group-level CSS rank criterion, crediting Theodore Yoder, and discuss
the lack of a fast general LC-CSS decision method in that work. Their
four-qubit non-CSS example is a preflight control here. This source statement
is not proof that no subsequent general algorithm exists.

[Dasu and Burton, section 3 and section 4](https://arxiv.org/html/2507.10519v1#S3)
already characterize CSS by invariance under the same rank-one projection at
every site, using an endomorphism-algebra framework attributed to Rains.
Their classification restricts equivalence to a uniform single-qubit gate.
Our site-dependent formulation builds on that existing idea; we do not claim
to have invented algebraic CSS recognition. A broader prior-art and complexity
review, plus external scrutiny, is still required.

## Claim (binary stabilizer groups, arbitrary generator basis)

Let S be an isotropic linear subspace of F2^(2n), representing a valid
stabilizer group modulo phases. Coordinates at each qubit are a row (x,z).
Then S is equivalent to a CSS group under arbitrary single-qubit Clifford
gates if and only if there is a site-local linear map P whose 2x2 blocks
are rank-one idempotents and S P is contained in S.

Proof, forward: if S C is CSS for a block-local invertible C, it is invariant
under P0 = diag(1,0) at every site. Set P = C P0 C^(-1). Then S P is contained
in S, and every block is a conjugate of a rank-one idempotent.

Proof, converse: each rank-one idempotent over F2 has one-dimensional image
and kernel with zero intersection. Choose their respective basis vectors as
the two columns of C at that site. Thus P C = C P0. All invertible 2x2
binary matrices have determinant one and represent single-qubit Cliffords
modulo Pauli phases. It follows that S C is invariant under P0 and I-P0.
Every stabilizer splits into its pure-X and pure-Z parts within S C, so S C
is CSS. This allows arbitrary changes of stabilizer generators, not just
making the supplied rows individually pure. Phases do not change CSS support.
Adding qubit permutations does not change the existence question, because
permutations preserve CSS and can be commuted past local gates.

## Exact reduction and certificate

Every rank-one idempotent has the form

```text
P_i = [ a_i      b_i ]
      [ c_i  1 + a_i ]        over F2, with b_i c_i = 0.
```

Trace one is necessary. Its determinant is b_i c_i because a_i^2=a_i;
trace one and determinant zero imply idempotence by the 2x2 characteristic
identity. There are six allowed blocks. Trace one alone is not sufficient:
the two b_i=c_i=1 blocks must be rejected, not rounded to a valid gate.

For every generator g=(x,z) and every ordinary dot-product annihilator
w=(u,v) in S-perp, invariance requires (g P) dot w = 0. Explicitly,

```text
sum_i [ (x_i u_i + z_i v_i) a_i
      + x_i v_i b_i + z_i u_i c_i ] = sum_i z_i v_i.
```

This is affine linear in 3n bits. An ordinary annihilator basis and a
stabilizer basis suffice. Inconsistent linear constraints certify that no
local Clifford to CSS exists, without enumerating patterns. The certificate
is a list of generator/annihilator pairs whose equations XOR to 0=1.

If the system is consistent, enumerate its d-dimensional affine solution
space and require b_i c_i=0 at every site. This is **exponential in d** in
the worst case, not a claimed polynomial-time complete algorithm. Above the
registered dimension or wall bound return UNRESOLVED, never non-CSS. A
successful point gives explicit local gates; verify their transformed
stabilizer group by the known CSS rank equality.

For an exhausted small affine space, retain the independent original
constraints. The verifier independently solves that necessary subsystem;
if none of its assignments is an allowed projector, non-equivalence follows
even without trusting the search solver's claims of constraint completeness.

## Implementation and independent falsification

`lc_projector.py` uses packed integer rows, highest-bit elimination and Gray
code enumeration. `lc_certificate_check.py` does not import it. The checker
uses dense binary matrices for commutation, row ranks, witness transforms,
annihilator membership and constraint formation. Its affine proof checker
uses lowest-bit elimination and ordinary binary assignment enumeration.

Preflight compares named codes and 48 seeded small commuting codes against
direct enumeration of all 6^n Clifford assignments until a witness is found
or the space is exhausted. Controls include the five-qubit perfect code,
Cross–Vandeth's four-qubit negative example, Bell and [[4,2,2]] codes, and
mixed-local-Clifford, row-scrambled Steane generators. Invalid commutation,
tampered certificates and unresolved resource limits are tested explicitly.
These are independent implementations, **not independent investigators**.

The public PBB matrices are constructed twice from polynomial terms in the
regular representation of Z_ell x Z_m. Choosing the inverse regular shift
instead amounts to simultaneous row and qubit relabeling, preserving the LC
question. Both implementations must agree exactly under our stated convention;
commutation and n-k rank must match every catalog record. Distance claims are
not used as proof or remeasured. Original JSONL bytes are pinned by the upstream
Git blob; the Apache-2.0 license is retained in `external/QCODE_LICENSE.txt`.

## What this could and could not establish

A completed, validated audit may strengthen this particular public catalog's
classification from restricted-family evidence to full LC evidence. That is
not a novel code, physical error-correction gain, superiority over all existing
solvers, formal machine-checked theorem, or consumer/enterprise indispensability.
The full-mission gates stay false. The public catalog is not a held-out
product benchmark. An algorithmic survivor would next need stronger prior-art
review, independent code families and independent expert reproduction.
