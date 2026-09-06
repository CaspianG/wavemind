# Independent review request — draft, not sent

Purpose: critical mathematical and prior-art review, not endorsement or
marketing. No author, organization or researcher has received this draft.
Sending it, sharing repository contents, or arranging a collaboration requires
the user's approval and an agreed recipient/channel.

## Proposed request

We have a candidate polynomial criterion for deciding whether an arbitrary
binary stabilizer subspace is equivalent to some CSS subspace by a tuple of
single-qubit Cliffords. We would appreciate an attempt to find an error or
identify an existing result that implies it. We are not claiming novelty or
independent validation.

Let E be the full algebra of block-diagonal 2x2 binary linear maps preserving
S. Let A be its affine slice with trace one on every block, written
T_i=[[a_i,b_i],[c_i,1+a_i]]. The proposed criterion is: a rank-one projector
at every site exists iff A is nonempty and no site has both b_i and c_i
identically one throughout A.

The argument uses G(T)=I+T^2+T, which is a central scalar mask selecting the
rank-one sites. For an affine basis T0+span(V1,...,Vd), the d+1 maps T0 and
T0+Vj cover every locally feasible site. Partitioning these masks within E
constructs the projector. Ordinary elimination gives a claimed O(n^4) field
operation bound, with short linear certificates for the negative cases.

Could you assess the following?

1. Is the local-to-global argument valid for the full preserving algebra,
   including arbitrary rank r<n, degenerate codes, zero subspaces, and free
   qubits? Is the CSS equivalence step missing any assumption?
2. Does this follow from Bouchet-type constrained equivalence, finite-algebra
   decomposition/idempotent lifting, or another known result? If so, what is
   the exact reduction and reference, including the binary-field case?
3. Is there an established implementation for the same recognition task
   against which the procedure should be tested?
4. What smallest structural counterexample or additional falsifier would
   distinguish a valid general result from the finite evidence we have?

## Evidence available for review

- [Frozen proof and caveats](LC_STITCHING.md), source SHA
  `90579911ad56ae2ef85e0c6f96c5c86d98cec178`.
- [R5 catalog audit](LC_PROJECTOR_R5_RESULTS.md): 368 source-pinned catalog
  entries, 11 positive and 357 negative certificates, no extra hidden CSS code.
- [R6 finite audit](LC_STITCHING_R6_RESULTS.md): 34,047 locally generated
  cases, with the original main-corpus positive-branch gap explicitly retained.
- [R7 adversarial frames](LC_ADVERSARIAL_R7_RESULTS.md), source SHA
  `f7726d79f2db3b57d24eca12f8973a70170b7484`: 96 guaranteed hard cases within
  384 constructed frames; dense checks of intermediate maps and witnesses.
- [Precise source comparison and failed shortcut](PRIOR_ART_THEOREM_AUDIT.md).
- [Reproduction and read-only audit commands](README.md#reproduce-or-audit).

Independent checking programs here were written and run in the same project.
They are not independent investigator replications. There is no claim of
superiority over an executed state-of-the-art package, quantum hardware gain,
consumer/enterprise benefit, or scientific admission.

## Sharing boundary

If approved, share only the agreed proof, source, public-source examples and
synthetic/QEC audit material. Do not include private account data, credentials,
the broader workspace, protected LongMemEval contents or unrelated product
history. A live public link must be verified before it is inserted into a sent
request; local file links above are for preparation and are not public URLs.
