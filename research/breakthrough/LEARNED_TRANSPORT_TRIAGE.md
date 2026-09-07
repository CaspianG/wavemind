# Learned transport structure: close the unqualified claim, retain the task

Date: 2026-09-07. Parent: `a906b4d`.
Decision: learning stable features, choosing interventions and returning
uncertainty intervals are not by themselves a new scientific mechanism.
No new practical candidate is selected. This is a bounded prior-art triage,
not a proof that innovation in causal learning is impossible.

## Four close comparisons

### Invariant features can already be learned

[Rojas-Carulla et al., JMLR 2018](https://jmlr.org/papers/volume19/16-432/16-432.pdf),
sections 2, 2.1 and 3, assumptions A1/A1'/A2, Theorem 1 and Algorithm 1.
The paper distinguishes invariance in training environments from invariance
in the unseen target. Its adversarial optimality statement assumes the latter;
training data cannot test that target assumption. It also gives a search for
invariant predictor subsets. Thus “learn the stable subset” is already a
method, while assuming its future stability does not certify a hidden target
mechanism change. The inspected main theorem is a prediction result, not
safe execution of a repair procedure.

### Active interventions and reuse of accepted hypotheses already exist

[Gamella and Heinze-Deml, NeurIPS 2020](https://proceedings.neurips.cc/paper_files/paper/2020/file/b197ffdef2ddc3308584dce7afa3661b-Paper.pdf),
sections 1.1-4 and the algorithm outline on printed page 6. A-ICP chooses
interventions from currently accepted predictor sets. Its setting excludes
interventions on the response mechanism; the structural model uses independent
noise. The paper distinguishes graphical stability from distributional
invariance and adds stability-faithfulness for the corresponding interpretation.
It reuses previously accepted subsets and corrects repeated testing over the
specified iteration horizon. Its error statement excludes false discovered
parents with high probability, not all harmful actions or all missed causes.

**Consequence:** active testing plus retained hypotheses is not a new memory
mechanism. Comparing only with random interventions would not resolve novelty.
Test informativeness and the permitted interventions must be part of a real
task specification, not privileged information silently given to a candidate.

### Partial graph knowledge is not an untouched identification problem

[Jaber, Zhang and Bareinboim, ICML 2019](https://proceedings.mlr.press/v97/jaber19a.html),
publisher abstract only. The authors give a complete identification algorithm
given a partial ancestral graph, representing a causal equivalence class.
This is a direct warning against claiming that all prior work requires one
fully known graph. It is not, by itself, a complete audit of transport across
unknown changing domains, finite-sample graph learning, or safe repair.

### Approximate transport with declared mechanism uncertainty is current work

[Felekis et al., arXiv:2608.15645v1](https://arxiv.org/html/2608.15645v1),
abstract, setup discussion and section 12 limitations/future work reviewed.
This August 2026 preprint studies approximate model-level transport with
target uncertainty and query intervals. Its stated limitations include linear
models/maps, a true or accurately estimated graph and a trusted source model;
source estimation uncertainty is not included in the final interval. Learning
the ambiguity geometry and adding source uncertainty are explicitly discussed
as future work. These are reported scope statements, not a reproduction or
our endorsement of its proofs. No claimed numerical gain is reused here.

**Consequence:** a possible extension needs a precise theorem or empirical
separation. “Account for uncertainty on both sides” alone is a known research
direction, not an established contribution of this project.

## Access and validation boundary

The PDF-reading workflow was used to inspect the two older papers after their
arXiv HTML requests failed. Relevant extracted sections, assumptions and
algorithm text were read; screenshot attempts did not produce usable displayed
page images and included cache/internal errors. No visual-layout verification
is claimed. The newer work was inspected in HTML; the PAG source was read at
abstract depth only. None of their code was downloaded or executed, and no
GitHub access restriction was bypassed. This is not an exhaustive literature
survey or external scientific review of our work.

## Why there is no next registered experiment yet

The earlier audits already reject unqualified scoped safety, cached decision
novelty, fixed-model diagnostic novelty, and automatic QEC-to-workflow benefit.
The remaining broad learned-structure idea also has close predecessors. There
is no current new assertion with a justified real consumer/enterprise input
model to freeze. Manufacturing another favorable synthetic distribution would
not test the actual mission. Existing failed runs remain failed, and all
stored registered runs have terminal result records; no live experiment handle
is being waited on in this turn.

This does not mean all possible mathematical work has been exhausted. It means
the specified candidates and immediate local alternatives do not currently
justify another decisive experiment toward the two full gates without the
missing external inputs. R8 remains a separate theorem candidate, with proof,
source, counterexample searches and an unsent critical-review packet.

## Recurring external prerequisites and resumption

The same missing requirements were recorded in three consecutive passes:

1. `2e87fbc`, [workflow bridge audit](WORKFLOW_BRIDGE_AUDIT.md): no real consumer
   or enterprise task data and no approved external reviewer.
2. `a906b4d`, [safe-transfer audit](SAFE_TRANSPORT_PRIOR_ART_AUDIT.md): task,
   observation/intervention contract and reviewer still absent; a direct user
   question requested both real processes.
3. This pass: no new user answer, independent dataset, approved recipient or
   externally produced review has arrived. The last bounded learned-structure
   triage does not supply a novel practical claim.

Further independent validation is blocked on these external prerequisites,
not on a pending process, a test failure to conceal, or a smaller substitute
goal. Resume on either actionable input:

- **Practical track:** one personal and one enterprise process, current
  procedure, owner-defined success/safety outcomes, anonymized examples and
  the allowed observations/interventions. Start with descriptions; passwords,
  tokens and private customer records are not needed.
- **Scientific track:** a specific qualified reviewer and an approved sharing
  channel/scope for the [prepared packet](EXPERT_REVIEW_PACKET.md), or an
  independently produced technical critique to address. A public author email
  is not permission to send repository contents.

On resumption, check the received evidence, refine the exact assertion and
strong comparator, then preregister before new outcome collection. Both
scientific breakthrough and mass indispensability remain required and false.
The objective is not completed or redefined by this handoff.
