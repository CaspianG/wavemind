from benchmarks import scientific_mab_v12_development as mab
from benchmarks import scientific_memops_v12_development as memops
from wavemind.scientific_runtime import ScientificCandidateMode


def test_v12_runners_bind_v12_protocol_and_frozen_candidate_mode():
    assert mab.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v12.json"
    assert mab.runner.ARTIFACT_SCHEMA == "wavemind.memoryagentbench_development.v12"
    assert memops.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v12.json"
    assert memops.runner.CANDIDATE_MODE is (
        ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT
    )
    assert memops.runner.ARTIFACT_SCHEMA == (
        "wavemind.scientific_memops_v12_development.v1"
    )
