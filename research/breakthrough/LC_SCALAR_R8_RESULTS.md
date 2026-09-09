# R8: simpler recognition argument, narrower novelty claim

Date: 2026-09-07. Status: preregistered falsifier completed, full read-only
replay passed. Both mission gates remain false.

## Decision first

The scalar-component alternative agrees with all tested exact answers.
It reduces the remaining nonlinear choice to at most six linear feasibility
systems per indecomposable support. R6's masks therefore select among actual
direct-sum components; the difficult R7 frames are not evidence of resolving
coupled choices across an indecomposable code.

The decomposition foundation is known: [Mirandola-Zemor, section 2.3,
Lemmas 2.7 and 2.10](https://arxiv.org/pdf/1501.06419v2). R8 applies it to
the paired-coordinate scalar algebra and derives an anchor consequence using
Cayley-Hamilton. This is our internal structural comparator, not an external
package run. The remaining possible contribution is the recognition theorem,
its proof and certificates, subject to prior-art and independent expert review.

## Frozen protocol and execution

- Source frozen **before main generation**:
  `fff2c991506344b7f69be6c4357bd52c1f91eb8b`.
- [Protocol](protocol_r8.json), [proof and boundary](LC_SCALAR_COMPONENTS.md),
  [runner](experiment_r8.py), [independent dense checker](lc_scalar_check.py).
- Seven preflight tests passed before freeze. Their code cases were known
  four- and five-qubit controls outside the complete n<=3 main corpus.
- Main run: **7.7378895 seconds**, Windows, Python 3.13.2, NumPy 2.5.2.
  This elapsed time is not a comparative speedup or uncertainty estimate.
- No paid/model/hardware calls, no new LongMemEval execution, no new external
  task data and no new dependencies. R5-R7 sources stayed byte-for-byte frozen.

## Outcomes

| Registered population / check | Result |
|---|---|
| All linear subspaces of F2^(2n), n=1,2,3 | 5 + 67 + 2825 = **2897**, unique by complete finite spans |
| Exact local-frame assignments | **612642**, all 6^n frames for every small subspace |
| Small-subspace answers | **2681 positive, 216 negative**, no disagreement with the component algorithm or R6 theorem-level reconstruction |
| Physical stabilizer subspaces among those inputs | **549; all 549 positive**; unchanged public R6 solver and separate certificate verification agree |
| Reused R7 hard inputs | **96/96 positive**, exact known number and size of independent components recovered from generators alone |
| Maximum anchor systems over a whole input | **8** in this corpus; theoretical bound is six per component |
| Largest component tested | **6 sites**, not a large indecomposable-code benchmark |

The 216 small negative examples are **non-isotropic linear subspaces**, not
216 physical stabilizer codes. The negative five-qubit stabilizer was a
preflight control, not part of this new main denominator. Existing R5/R6
negative evidence remains separate and unchanged.

Each alternative result was checked by independently rebuilding dense
preservation constraints, checking scalar-algebra nullity and complete disjoint
indicators, verifying projected-rank additivity, and auditing each attempted
anchor system. Infeasible anchors carry an explicit XOR contradiction; feasible
anchors carry a preserving local rank-one idempotent and a directly checked CSS
frame. The small oracle uses finite span membership instead of the solvers'
Gaussian-elimination criterion. Isotropic cases also use the frozen public R6
solver; non-isotropic cases use only its theorem-level affine/stitching route,
not a claim that its public API accepts noncommuting stabilizers.

The two-Bell preflight ablation exhibits a preserving trace-one map with a
rank-one block at one anchor but rank two on another component. Thus the
one-anchor argument without the independent-support condition is false.

## Evidence and reproduction

[Receipt](runs/r8/receipt_start.json) and [result](runs/r8/result.json) include
the environment, exact source and output hashes. Stored files:

| File | Bytes | SHA-256 |
|---|---:|---|
| `runs/r8/inputs.jsonl` | 286761 | `4a3ee414420192e67163f6a9c25dbc0769a60e81398dc5a04d2363bcb8d87027` |
| `runs/r8/raw.jsonl` | 2561441 | `8ce2370274908cdb0fb61266f31ec9330dd3bfcce7307fc04c7eb345db6f03b5` |

```sh
python research/breakthrough/verify_r8.py
python -m pytest -q research/breakthrough
```

The verifier checks hashes against both the receipt and Git's frozen commit,
regenerates every input, repeats every exact small local-frame enumeration,
and rechecks every stored result. It does not accept a green status string
as evidence. Post-run regression tests deliberately alter raw bytes and a
summary count; neither is permitted to validate. For a fresh run, use a clean
checkout of the frozen SHA and run `experiment_r8.py --output NEW_DIRECTORY`;
existing output directories are rejected.

The post-run research suite completed with **49 passed, 0 failed** in 18.84 s,
including both tamper regressions. Ruff passed. This test count is software
validation, not a new scientific or mass-indispensability admission.

## Plain Russian explanation

Вместо соединения многих частичных ответов можно сначала найти независимые
части кода. Для каждой части достаточно проверить до шести вариантов на
одном кубите, каждый раз решая линейные уравнения. Это делает рассуждение
проще и показывает, что «трудность» прежнего R7 зависела от представления
задачи. Само разложение на части известно из литературы.

Полный небольшой перебор не нашёл контрпример. Это усиливает кандидата на
корректный общий алгоритм, но не доказывает первенства. Мы не получили здесь
измеренное ускорение квантового компьютера или AI-помощника и не проверили
массовую либо корпоративную незаменимость.

## Next decision

Update the unsent review packet to lead with this simpler proof and explicitly
credit the known scalar-decomposition lemma. Next investigate whether the
remaining one-anchor consequence is already implicit in the closest
endomorphism-algebra results. An external reviewer/package is still needed;
the current investigator cannot supply its own independent endorsement.

Do not spend the next experiment merely adding positive direct-sum frames.
First state a concrete consumer and enterprise workflow in which LC-CSS
recognition is necessary to an observable outcome, or explicitly reject that
bridge and investigate a different mechanism for the unchanged full goal.
At present there is no such demonstrated bridge: the mass-indispensability
gate has not moved, and no QEC test count can stand in for it.
