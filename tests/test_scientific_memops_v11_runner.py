from benchmarks import scientific_memops_v11_development as runner
from wavemind.scientific_runtime import ScientificCandidateMode


def test_v11_memops_runner_binds_v11_protocol_mode_and_schema():
    assert runner.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v11.json"
    assert runner.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT
    )
    assert runner.runner.ARTIFACT_SCHEMA == (
        "wavemind.scientific_memops_v11_development.v1"
    )
    assert runner.runner.CLUSTER_GATE_KEY == (
        "minimum_independent_clusters_per_family"
    )
