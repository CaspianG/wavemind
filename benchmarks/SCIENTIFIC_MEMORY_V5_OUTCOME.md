# Scientific memory v5 development outcome

Status: `failed_development_gate` (one of two required benchmark families passed).

Candidate: `atomic-batch-hierarchical-proof-state-reconciler-v5`

Candidate source SHA: `0a6e6183b4bb46c2c8b2e7e5ca246d3dea3d1950`

Protocol digest: `2b0af0171226eee0d1cc1acd134c196982fb095454b885a136662fb51e8e0331`

No validation or final split was opened. No production promotion occurred.

## MemoryAgentBench Accurate Retrieval

The same five independent development contexts were run three times at the
exact candidate SHA. Every run produced paired effects
`[0, 1, 0, 1, 1]`: mean uplift `0.60`, frozen paired cluster-bootstrap 95%
CI `[0.20, 1.00]` (2,000 repeats, seed 17), intervention coverage `1.00`,
zero negative effects, zero production-index records, and zero false verified
promotions. All 15 measured candidate recalls were below the frozen 1,000 ms
budget; the observed maximum was 418.66 ms.

Evidence:

- run 1 raw SHA-256: `7973997f107e1b258a4fc3c0adc7fde1d315adf77404a8e01c07245760557036`
- run 1 artifact SHA-256: `72072b450054bc6497c8059d7390dcab9caf42056e436e6489ae58f1001f68c1`
- run 2 raw SHA-256: `eac4ba6be8bdd6ec719565f1ea5d011ad4f5d56a4fba1ab6bda509c871639851`
- run 2 artifact SHA-256: `bd99dc69b64db22542ba913ec831df1abb2e508c78819e3e2be3ec0f71840da2`
- run 3 raw SHA-256: `ca6ff56eeb59f25c2d7835d563fbf9e076e66cbdaf7c26c855e2ad53979c6dc4`
- run 3 artifact SHA-256: `ecb3a858b099fb0690cd0d05b074bbe4f8a14f2a32bea0eb027850cfec8daa71`

## MemOps Forget

The first Forget case for each of the first five lexicographic development
subjects (`A04`, `A06`, `A07`, `A13`, `A14`) produced paired effects
`[0, 0, 1, 0, 0]`: mean uplift `0.20`, one positive effect, four ties, and no
negative effect. The lower confidence bound is not strictly positive, so this
family failed the frozen gate.

Evidence:

- raw SHA-256: `942af7abb7800c214a22373c5a1087335f336c363e245a062fae11a4a6714841`
- artifact SHA-256: `debf63097cc3bf5cb35d73bcdb866f58a3b95354e366918bd4494d0152ffff83`
- official upstream SHA: `312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35`

## Causal failure diagnosis

The atomic batch removed the v3/v4 ingestion bottleneck and the hierarchical
compiler fixed the v2 absent-retrieval defect. The remaining MemOps failure is
selection over a distractor-heavy session corpus. For A04 the selector chose
sessions 44, 45, and 46, which contain unrelated culture, literature, and
mindfulness dialogue. The pertinent state transitions were in session 4
(Portland residence) and session 15 (the explicit request to forget Tucson).
The generic `0.25 * recency` term overwhelmed weak lexical alignment for a
generic summary query. Thus v5 had a real intervention but often supplied the
wrong intervention.

The next candidate must identify explicit memory-operation dialogue and carry
later forget/remove/delete obligations into retrieval. It may not inspect gold
operations, expected answers, scorer outputs, or held-out rows.
