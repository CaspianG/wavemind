from benchmarks import scientific_mab_v13_development as mab
from benchmarks import scientific_memops_v13_development as memops


def test_v13_runners_bind_protocol_family_source_and_schema():
    assert mab.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v13.json"
    assert mab.runner.FAMILY_KEY == "memoryagentbench_summarization"
    assert mab.runner.REQUIRED_SOURCE == "infbench_sum_eng_shots2"
    assert mab.runner.ARTIFACT_SCHEMA == "wavemind.memoryagentbench_development.v13"
    assert memops.runner.PROTOCOL_PATH.name == "scientific_memory_protocol_v13.json"
    assert memops.runner.ARTIFACT_SCHEMA == (
        "wavemind.scientific_memops_v13_development.v1"
    )
