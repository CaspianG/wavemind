# WaveMind Structured Memory Report

Generated: `2026-07-08T20:13:52Z`.

Structured-memory rows come from the checked-in scale-readiness artifact. They prove typed payload routing, provenance, persistence, temporal recall, and graph traversal on the deterministic fixture; they do not claim full production multimodal model quality.

## Summary

- Status: `pass`.
- Modalities: `image, audio, table, event, video, 3d, graph`.
- Structured precision@1: `1`.
- Cross-modal precision@1: `1`.
- Precomputed-vector precision@1: `1`.
- Temporal event precision@1: `1`.
- Knowledge-graph precision@1: `1`.
- Cross-modal avg latency: `1.762 ms`.
- Temporal avg latency: `0.666 ms`.
- Knowledge-graph avg latency: `0.708 ms`.

## Gate Checks

| check | status | value | target |
|---|---|---:|---:|
| modalities | `pass` | `7` | `>= 7` |
| structured_precision_at_1 | `pass` | `1` | `>= 1.0` |
| cross_modal_precision_at_1 | `pass` | `1` | `>= 1.0` |
| cross_modal_vectors_persisted | `pass` | `1` | `>= 1.0` |
| cross_modal_provenance | `pass` | `1` | `>= 1.0` |
| precomputed_vector_precision_at_1 | `pass` | `1` | `>= 1.0` |
| precomputed_vector_persisted | `pass` | `1` | `>= 1.0` |
| encoder_contract_ok | `pass` | `1` | `is True` |
| encoder_contract_target_precision_at_1 | `pass` | `1` | `>= 1.0` |
| encoder_contract_global_precision_at_1 | `pass` | `1` | `>= 1.0` |
| encoder_contract_margin | `pass` | `0.811` | `>= 0.2` |
| temporal_event_precision_at_1 | `pass` | `1` | `>= 1.0` |
| temporal_event_persistence | `pass` | `1` | `>= 1.0` |
| temporal_event_provenance | `pass` | `1` | `>= 1.0` |
| knowledge_graph_precision_at_1 | `pass` | `1` | `>= 1.0` |
| knowledge_graph_path_precision_at_1 | `pass` | `1` | `>= 1.0` |
| knowledge_graph_persistence | `pass` | `1` | `>= 1.0` |
| knowledge_graph_provenance | `pass` | `1` | `>= 1.0` |
| asset_manifest_verified | `pass` | `1` | `is True` |

## Coverage

| area | evidence |
|---|---|
| Typed payloads | `7` queries across `7` modalities. |
| Cross-modal routing | `7` typed queries, persisted vector rate `1`, provenance `1`. |
| External vectors | `4` strict precomputed-vector queries over `image, audio, video, 3d`. |
| Encoder contract | target@1 `1`, global@1 `1`, margin `0.811`. |
| Temporal events | around/window/recency/interval `1/1/1/1`. |
| Knowledge graph | direct/two-hop/three-hop/predicate `1/1/1/1`. |

## Next Production Step

Run the same contract on real CLIP/audio/video/3D production encoders and larger object-store-backed corpora before claiming broad multimodal model quality.
