from benchmarks import scientific_mab_v15_development as mab
from benchmarks import scientific_memops_v15_development as memops
from wavemind.scientific_runtime import ScientificCandidateMode


def test_v15_runners_bind_protocol_mode_family_source_schema_and_repaired_gate():
    assert mab.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v15.json"
    assert mab.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
    )
    assert mab.runner.FAMILY_KEY == "memoryagentbench_summarization"
    assert mab.runner.REQUIRED_SOURCE == "infbench_sum_eng_shots2"
    assert mab.runner.ARTIFACT_SCHEMA == "wavemind.memoryagentbench_development.v15"
    assert memops.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v15.json"
    assert memops.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
    )
    assert memops.runner.ARTIFACT_SCHEMA == (
        "wavemind.scientific_memops_v15_development.v1"
    )
    assert memops.runner.CLUSTER_GATE_KEY == "minimum_independent_clusters_per_family"
