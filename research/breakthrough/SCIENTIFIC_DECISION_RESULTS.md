# R8 decision gate: local proof survives; novelty remains unreviewed

Executed 2026-09-07 from frozen source
`0692b111e141e4546a99c29a63359c2b935d46f4`. The
[exact claim and proof](SCIENTIFIC_DECISION_GATE.md), protocol, runner,
and five preflight tests were committed before generating main inputs.
This report was written after execution.

## Decision

Keep the minimal recognition claim as a **locally proved candidate** for
independent review. No counterexample was found in the frozen test. Do not
claim that scalar decomposition is new, that finite tests prove the general
theorem, or that a new scientific capability has been independently admitted.
The scientific breakthrough gate and mass-indispensability gate remain false.

The step-by-step proof makes the exact burden visible: known scalar atoms,
constant determinant on each atom for trace-one algebra elements, six linear
anchor systems, and an explicit row-action CSS witness. A published finite-
algebra reduction could still remove the residual novelty claim entirely.

## Frozen finite results

| Check | Observed result |
|---|---|
| All unital linear spaces for one/two sites | 29,228 (16 + 29,212) |
| Spaces closed under multiplication | 519; all audited, no filtering by outcome |
| Closed algebras without an all-site rank-one idempotent | 223 |
| Trace-one element/atom checks | 5,044, no contradiction |
| Six-anchor feasibility vs every-element oracle | All 519 agree |
| Explicit removed-assumption controls | Both break the weakened implication as predicted |
| Seven-site graph inputs | 8 frozen hash-derived inputs plus C7 and star |
| Complete graph LC orbits | 10/10 resolved; 10 distinct orbits |
| Physical answers | 5 CSS-equivalent, 5 not LC-CSS |
| Indecomposable physical negatives | Four inputs with a single component of size 7 |
| Other physical negative | One input with component sizes 6 and 1 |
| Dense certificate audit | All ten graph answers verified |
| Resource-limited/unresolved inputs | Zero |

Main runner time was 1.649 seconds on this local environment, not a speedup
comparison. Nonclosed spaces remain in the raw file as rejected-domain records.
The exact finite-element oracle uses direct matrix multiplication; graph truth
uses complete edge-toggle LC orbits and bipartiteness, not projector equations.
Some helpers are shared with earlier local tests, so these are distinct checking
methods within one project, not independent investigator reproductions.

The n=7 negatives close the specific physical-negative coverage gap of R8's
small isotropic corpus. They do not establish large indecomposable performance,
proper-code coverage at arbitrary rank, or population-wide failure rates.
Previously preserved R5/R6 evidence is not counted as new cases here.

## Integrity and reproduction

- Raw: `runs/decision_gate/raw.jsonl`, 29,239 records (all spaces, ten graphs,
  and one paired ablation record).
- SHA-256: `83bad867a3e74c7540a48d583929c30f23db45aadb30c7d9c012edb3cc554c52`.
- Receipt pins all nine source files, the source commit, Python 3.13.2,
  platform, and UTC start. Frozen R8 dependencies were checked byte-for-byte.
- Full read-only replay regenerated every record, all ten graph orbits and
  certificate checks; source/raw hashes and the complete summary matched.
- Research suite including five new preflight tests: **61 passed**, 18.65 s.
  Ruff and `git diff --check` passed before the main run.

```sh
python research/breakthrough/decision_gate_falsifier.py --verify research/breakthrough/runs/decision_gate
```

For fresh reproduction, use a clean checkout of the source commit and run
the same program with `--output` naming a new directory. Never overwrite the
preserved run. Resource exhaustion is recorded as unresolved, not a negative
mathematical result or a pass.

## Next decisions, without declaring a breakthrough

1. Independent reviewer: verify steps 4–6 and try to give an exact known
   finite-algebra reduction. The review packet is still unsent; no external
   contact or data transfer is authorized.
2. If a new technical counterexample/critique arises, test its precise claim.
   Do not repeat finite positive tests merely to accumulate impressive counts.
3. Start the separately scoped public-workflow feasibility branch under a
   preregistered selection and measurement contract. A classification theorem
   has no demonstrated automatic benefit for WaveMind or its users.

## Коротко по-русски

Получился более простой и проверяемый кандидат на алгоритм: он определяет,
можно ли придать квантовому коду нужную CSS-структуру, и показывает почему.
Дополнительная проверка нашла и положительные, и отрицательные физические
примеры; во всех случаях ответы совпали с точным эталоном. Контрпримеров
не найдено. Но первенство результата и доказательство ещё должен проверить
независимый специалист. Ускорение AI-помощника, квантового устройства или
работы предприятия этими тестами не доказано.
