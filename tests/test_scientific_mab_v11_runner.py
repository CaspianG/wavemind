from benchmarks import scientific_mab_v11_development as runner
from wavemind.scientific_runtime import ScientificCandidateMode


def test_v11_mab_runner_binds_frozen_protocol_and_mode():
    assert runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v11.json"
    assert runner.CANDIDATE_MODE is (
        ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT
    )
