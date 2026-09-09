# Scientific decision gate: the residual R8 claim

Prepared 2026-09-07, before the additional falsifier below. This supersedes
the previous *local-work* pause, not any historical result. Independent
review and both mission gates remain open. No novelty admission is implied.

## Exact, falsifiable claim

Given L binary generators for an isotropic subspace S of F2^(2n), n >= 1,
there is a deterministic algorithm using O(L n^2 + n^4) F2 operations that
decides whether S is equivalent to **some** CSS subspace under independent
single-qubit Cliffords. It supplies either a tuple of invertible 2x2 binary
maps giving the CSS form, or a scalar-support decomposition and six explicit
inconsistent linear systems on a failing support.

The stronger linear-algebra statement holds without isotropy; such inputs
are not physical stabilizer codes. This is existence of a representation,
not code-distance improvement, a decoder, noise optimization, or a product
performance claim. Input ranks zero through n, redundant generators, and
unused sites are included. No fixed target CSS code is supplied.

**Residual novelty question:** is this recognition consequence already known
or implied by a published general algorithm? The scalar decomposition,
Cayley–Hamilton identity, and projector-to-CSS equivalence are not claimed
as inventions. Local derivation of a corollary is not a priority finding.

## Proof in checkable steps

1. Use row coordinates (x,z). Let E be the block-diagonal local maps T with
   ST contained in S. E is a unital associative F2-algebra: preservation is
   closed under addition and composition. Ordinary annihilators, not the
   symplectic dual, give complete linear equations g T w^t = 0.

2. Define B = {m : diag(m_i I2) belongs to E}. B contains 1 and is closed
   under pointwise products. Coordinates having the same values on every
   basis vector of B form an atom. For a occurring signature s, multiply
   each basis mask having s_j=1 and each complemented mask having s_j=0.
   This is precisely the atom indicator. Thus all atom indicators lie in B,
   are disjoint, sum to 1, and span B. This is the known subalgebra
   decomposition credited to Mirandola–Zémor, not new work here.

3. Each indicator preserves S. Consequently S is the direct sum of its
   restrictions S_C to the atoms C. E is the product of their full preserving
   algebras. A scalar mask on one restricted algebra extends by zero to E,
   so the scalar algebra on each atom consists only of 0 and I. Unused sites
   are singleton atoms, since their individual indicators preserve S.

4. On an atom take any preserving T whose block traces are all 1.
   Cayley–Hamilton over F2 gives

   ```text
   T_j^2 + T_j = det(T_j) I2
   I + T^2 + T = diag((1 + det(T_j)) I2).
   ```

   The latter belongs to the scalar algebra and is either 0 or I throughout
   C. Hence det(T_j) is constant on C. If one chosen anchor block has trace
   1 and determinant 0, so does every block. Each is an idempotent of rank
   exactly one: it is neither 0 nor I (both have trace 0).

5. Exactly six binary 2x2 matrices have trace 1 and determinant 0. For each
   anchor choice, preservation, trace at **every** site, and the four anchor
   entries are linear equations. If any system is consistent, every solution
   gives a local rank-one projector on that atom by step 4. If all six fail,
   no all-site rank-one projector can exist there. Projectors from different
   atoms assemble because of step 3. Gaussian elimination records an XOR of
   original equations yielding 0=1 for each inconsistent system.

6. For each projector P_j choose a nonzero column eigenvector of eigenvalue
   1 and then one of eigenvalue 0. The matrix G_j with these columns is
   invertible and P_j G_j = G_j D, D=diag(1,0). Thus (S G)D = (S P)G is
   contained in SG. Closure under D and I-D splits SG into X-only and Z-only
   parts, which is CSS. Conversely, if SG is CSS, P=G D G^-1 preserves S
   and has rank one at each site. GL(2,F2)=Sp(2,F2), so these binary maps are
   implemented by single-qubit Cliffords. Stabilizer signs do not obstruct
   the binary CSS split; this does not claim a specified signed target.

7. Reduce L generators in O(L n^2) field operations. There are at most
   O(n^2) scalar-preservation equations in n variables. On a component of
   size c, there are O(c^2) equations in 4c variables. At most six dense
   eliminations cost O(c^4). Sum c^4 <= n^4. Building restrictions and
   annihilators fits this bound. This is an arithmetic upper bound, not a
   benchmark or bit-complexity speedup over every existing implementation.

The same atom lemma holds in any unital subalgebra of a product of M2(F2),
not only in preserving algebras. Steps 2 and 4 are the smallest independently
testable core of the proposed recognition consequence.

## Prior-art decision

The existing [theorem applicability audit](PRIOR_ART_THEOREM_AUDIT.md)
and [R8 source comparison](LC_SCALAR_COMPONENTS.md) remain authoritative:
Mirandola–Zémor Lemmas 2.7/2.10 supply the decomposition; known conjugated
projectors supply the representation bridge. Supplied-pair LC equivalence
and uniform-on-all-sites Clifford tests are not automatically the same task.
The failed F4 generic-idempotent shortcut does not refute finite-algebra
algorithms. A possible reduction to such algorithms remains a real novelty
falsifier, not something dismissed by this proof.

**Pre-run decision:** a complete local proof candidate survives this audit.
No new general theorem of code decomposition or new physical capability
remains to claim. The only proposed scientific contribution is the precise
recognition consequence above; its priority and independent correctness
are UNREVIEWED. External review was not requested or simulated.

## Strongest remaining falsifiers and baselines

- Exhibit a unital preserving algebra where step 4 fails, or a CSS witness
  where necessity in step 6 fails. The next finite test exhausts all unital
  linear subspaces of M2(F2)^n for n=1,2, tests multiplication closure, and
  compares six-anchor feasibility with enumeration of **every** element.
- Test physical negative, indecomposable inputs missing from R8's small
  isotropic domain. The next test freezes eight hash-selected n=7 graphs,
  plus C7 and star controls; compare R8 with full per-input graph LC orbits.
  Orbit enumeration uses edge toggles/two-colouring, not projector equations.
- Retain all nonclosed spaces as rejected-domain records. Explicit controls
  remove closure or atom restriction and must break the corresponding lemma.
- Seek an exact published reduction for arbitrary rank, binary field,
  site-dependent maps, and an unspecified CSS target. This remains the
  strongest priority falsifier even if all finite tests pass.
- Full local-frame enumeration and complete graph orbits are exact small
  truth baselines, **not** efficient external SOTA packages. R6 is internal.
  No external same-task implementation or large-instance speedup is claimed.

The next cheap experiment is frozen in [decision_gate_protocol.json](decision_gate_protocol.json).
Results, failures, resource limits, and coverage gaps must be reported without
changing its inputs or relabelling them as consumer/enterprise evidence.

## Practical branch and registry state

The new instruction permits autonomous selection of public, licensed consumer
and enterprise workflows after this gate. Missing owner-selected workflows
is therefore no longer a local blocker. Selection criteria must be recorded
before choosing data or seeing measured outcomes. A public-data benchmark is
not a live pilot and does not by itself close the mass-indispensability gate.
The app goal registry was observed as `blocked`; the available status tool
cannot resume it. Local work continues under the new instruction, without
claiming that the registry has been changed or that either gate has passed.
