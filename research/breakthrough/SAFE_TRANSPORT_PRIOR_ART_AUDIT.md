# Safe reuse after change: no new mechanism selected yet

Date: 2026-09-07. Parent evidence: `2e87fbc`.
This is a targeted primary-source applicability review, not an exhaustive
literature clearance or a new experiment. The previous QEC bridge audit
rejected automatic practical transfer; this pass examines a more direct
agent-workflow direction without resurrecting the rejected R1/R2 cache.

## Decision

Do not promote “stored verified actions + a risk bound + baseline fallback”
as a scientific invention. Those ingredients already have close, substantive
theoretical predecessors. More importantly, their guarantees concern different
quantities. Combining them does not automatically certify the next action
after an unobserved change.

No new practical mechanism survives **as presently specified**. This is not
a claim that no future improvement in safe transfer is possible. The remaining
question must state what is newly learned or computed, from which observations,
under which externally justified change assumptions, and at what charged cost.
An implementation comparison is premature without that distinction.

## Source-to-claim mapping

Only the sections listed were substantively reviewed. None of these external
packages was executed. Their experimental results are not our results.

### 1. Baseline fallback is existing safe-policy methodology

[Laroche, Trichelair and Tachet des Combes, SPIBB, arXiv v5](https://arxiv.org/html/1712.06924v5):
section 2, Theorem 2, Appendix A.1 and the displayed proof in A.3. It constrains
policy changes at under-supported state/action pairs and provides a
high-probability approximate improvement bound in a specified unknown finite
MDP, relative to the baseline. The model has bounded reward and discounted
return. Its target is expected return, not absence of every unsafe event.
The displayed bound can be loose; fallback itself is not proof that the
baseline is safe after an arbitrary change to the transition mechanism.

**Decision:** reject baseline fallback plus stored experience as unqualified
novelty. A future proposal must compare at least this family, with identical
information and baseline access, and distinguish return from safety losses.

### 2. Exploiting factor structure is not an untouched gap

[Simão and Spaan, AAAI 2019](https://ojs.aaai.org/index.php/AAAI/article/view/4427):
publisher abstract reviewed, not the full proof. Factored SPIBB explicitly uses
independence structure for less conservative safe policy improvement; the
abstract states a parameter-count-dependent bound and reports potential
order-of-magnitude sample savings relative to a flat method. These are the
authors' claims, not reproduced measurements here.

[Wienhöft et al., 2305.07958](https://arxiv.org/abs/2305.07958): abstract reviewed;
the HTML full-text request failed. It proposes tighter SPI bounds and reduced
sample requirements. It is an additional mandatory comparator lead, not a
fully audited theorem or permission to assume the 2019 bound is best possible.

**Decision:** do not rename factor-aware reuse or a win over a flat baseline
as a novel 10x capability. Learning unknown, changing factor structure would
be a distinct claim requiring further literature and identifiable task data.

### 3. Conformal risk is not a per-history safety certificate

[Angelopoulos et al., Conformal Risk Control, v4](https://arxiv.org/html/2208.02814v4):
sections 1.1 and 2.1, Theorem 1. The main result concerns expected loss on a
new exchangeable loss function, with bounded, monotone, right-continuous losses
and an admissible most-conservative setting. It averages over calibration
and test randomness. This is not the same claim as a bound conditional on
every realized deployment history. Distribution-shift extensions exist in
the paper; they were not fully audited here, and the base theorem must not
silently be applied to an arbitrary changed environment.

**Decision:** the word “conformal” does not turn a recalled action into a
pointwise safe action. Record which theorem and assumptions actually apply.

### 4. Arbitrary-shift frequency control is already known, but is a different target

[Gibbs and Candès, ACI, v3](https://arxiv.org/html/2106.00170v3): section 2 and
section 4.1, Lemma 4.1 and Proposition 4.1 including its proof. With observed
errors and appropriate prediction-set extremes, its update bounds long-run
empirical miscoverage without distributional assumptions. The result is an
aggregate error-frequency guarantee, not a guarantee that the next prediction
is correct. Prediction sets can expand to the whole outcome space.

[Gibbs and Candès, DtACI, v3](https://arxiv.org/html/2208.08401v3): Theorems 3.1
and 3.2 reviewed. Step-size adaptation and local-interval regret already go
beyond fixed-step long-run calibration. Those results are not a zero-error
action certificate either. We have not reproduced their methods or datasets.

**Decision:** a new wrapper must not count abstention or a vacuous prediction
set as completed useful work. Report coverage, action completion and risk
separately; do not use a deliberately weak fixed-calibration baseline.

### 5. Anytime confidence concerns its declared estimand

[Howard et al., confidence sequences, v9](https://arxiv.org/html/1810.08240v9):
section 2's supermartingale setup and section 4.1, Theorem 4. For bounded
observations the latter covers the running average of conditional expectations,
uniformly over time; it explicitly permits unequal means and predictable
predictions. This is stronger than a fixed-time interval but still concerns
that average, not an unconstrained future conditional mean. Optional stopping
validity does not supply information about a newly changed action's outcome.

**Decision:** a time-uniform certificate must name its estimand. Evidence
about average observed risk cannot be relabeled as next-action safety.

### 6. Causal transport uses causal assumptions, not just provenance labels

[Bareinboim and Pearl, PNAS 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4941504/):
the section “Transportability and the Problem of Data Fusion” and the
selection-diagram discussion. The framework expresses what may differ
between domains and combines available observations and interventions to
identify a target effect when transport is possible. The paper describes
complete transportability procedures given such diagrams. The diagram and
data availability are inputs to the identification problem; attaching a
graph-shaped label to an action does not establish those assumptions.

**Decision:** known-graph transport and learning/verifying the graph must be
treated as separate tasks. No causal structure of a real user workflow has
yet been supplied or independently validated here.

## The guarantee mismatch, explicitly

| Available guarantee | Its object | What it cannot alone establish |
|---|---|---|
| SPI-style improvement | Expected policy return relative to a baseline in the modeled environment | No unsafe event after arbitrary mechanism change |
| Main conformal risk control result | Expected new exchangeable loss | Safety conditional on each selected history or subgroup |
| ACI/DtACI | Aggregate miscoverage or interval regret | Correctness of every next action; useful nonvacuous completion |
| Time-uniform confidence sequence | The stated parameter or running conditional-mean average | An unconstrained future risk after hidden change |
| Causal transport formula | Identified target effect under structural assumptions and available data | Truth of an unverified causal diagram |

These are not defects or refutations of the papers. They are boundaries on
our proposed use of their guarantees. The same-history/different-next-outcome
obstruction is already preserved in [H1/R3](DECISION.md); no new run or new
name is needed for that familiar nonidentifiability argument.

## Requirements before a new decisive experiment

For each real consumer and enterprise workflow, obtain:

1. An owner-specified task, success condition, safety losses and the actual
   current procedure. Abstention and “ask a human” must have measured costs.
2. What the learner observes before acting, which interventions are permitted,
   when outcome labels arrive, and which relevant changes can be hidden.
3. A justified model of change or independently collected changed-environment
   cases. Do not give the candidate the hidden change labels or true graph
   unless the comparator receives the same information.
4. A precise new assertion not already implied by the methods above: for
   example an independently supported computational/sample-complexity
   separation, not “combine memory and uncertainty.” No such assertion has
   yet been established for this practical track.
5. A preregistered primary resource/outcome, quality and safety noninferiority
   margins, unit economics, rollback verification, held-out construction,
   repetitions, uncertainty analysis and strong executed baselines. Numeric
   tolerances cannot be invented for an owner we do not have.

The two workflow descriptions/data and the approved scientific reviewer were
requested earlier and remain absent in the conversation. No external message
was sent, and no permission is inferred from a paper's public author address.
The QEC proof candidate remains separately available for that review.

## Consequence for the next action

This pass rules out the unqualified composite claim and corrects the baseline
set. It does not select a scientifically novel practical mechanism. No model
call, paid experiment, hardware run or LongMemEval rerun was made. R1–R8 and
the exact workflow-boundary records are unchanged.

The next practical experiment needs the concrete task and observation contract
above. Pending it, the bounded remaining literature question is whether a
**learned change/transport structure** can be identified with the available
interventions and improve over established factored/robust methods. That is
still a question, not a survivor or authorization to invent a favorable model.
Independent novelty/correctness review of R8 and real consumer/enterprise
measurements remain mandatory for the original two gates.

Follow-up: [learned-structure triage](LEARNED_TRANSPORT_TRIAGE.md) now adds
invariant-feature learning, active ICP, identification under partial graph
knowledge and a 2026 approximate-transport comparator. The broad remaining
idea is not selected as a novel mechanism. External task/observation inputs
and approved independent scrutiny are required to resume the next decisive
validation; the full objective is unchanged.
