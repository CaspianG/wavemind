from benchmarks import scientific_mab_v16_development as mab
from benchmarks import scientific_memops_v16_development as memops
from wavemind.scientific_runtime import ScientificCandidateMode


def test_v16_runners_bind_composite_candidate_and_both_modern_gate_keys():
    assert mab.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v16.json"
    assert mab.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
    )
    assert mab.runner.CANDIDATE_ID_OVERRIDE == (
        "target-scoped-state-verification-agent-v16"
    )
    assert memops.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v16.json"
    assert memops.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.TARGET_SCOPED_OPERATION_AGENT
    )
    assert memops.runner.CLUSTER_GATE_KEY == "minimum_independent_clusters_per_family"
    assert memops.runner.CI_GATE_KEY == (
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    )
    assert memops.runner.QUESTION_SELECTION == "state-verification-v3"
