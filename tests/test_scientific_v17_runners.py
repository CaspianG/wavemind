from benchmarks import scientific_mab_v17_development as mab
from benchmarks import scientific_memops_v17_development as memops
from wavemind.scientific_runtime import ScientificCandidateMode


def test_v17_runners_bind_composite_candidate_and_safe_trajectory_contract():
    assert mab.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v17.json"
    assert mab.runner.CANDIDATE_MODE is ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
    assert memops.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v17.json"
    assert memops.runner.CANDIDATE_MODE is ScientificCandidateMode.TARGET_SCOPED_OPERATION_AGENT
    assert memops.runner.QUESTION_SELECTION == "state-verification-v4"
    assert memops.runner.TRAJECTORY_SEQUENCE_COVERAGE is True
    assert memops.runner.CLUSTER_GATE_KEY == "minimum_independent_clusters_per_family"
    assert memops.runner.CI_GATE_KEY == "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
