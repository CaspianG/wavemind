from __future__ import annotations

from wavemind.scientific_answer_transducer import (
    canonicalize_query_constrained_answer,
)
from wavemind.scientific_memoryagentbench import (
    MemoryAgentBenchDevelopmentUnit,
    _dataset_config,
)


OPTIONS_QUERY = (
    "Choose the next event from "
    "['Pascal instructed the team to adjust the rigging.', "
    "'Pascal ordered the crew to take in sail.', "
    "'Pascal commanded the crew to secure the cargo.']"
)


def test_v9_transducer_recovers_exact_query_option_from_clear_paraphrase():
    result = canonicalize_query_constrained_answer(
        OPTIONS_QUERY,
        "Pascal commanded the crew to take in sail.",
    )

    assert result.applied is True
    assert result.output == "Pascal ordered the crew to take in sail."
    assert result.similarity >= 0.5
    assert result.winner_margin >= 0.1
    assert result.candidate_count == 3


def test_v9_transducer_fails_closed_for_ambiguous_or_unconstrained_output():
    ambiguous = canonicalize_query_constrained_answer(
        OPTIONS_QUERY,
        "Pascal spoke to the crew.",
    )
    unconstrained = canonicalize_query_constrained_answer(
        "What happened next?",
        "The crew adjusted the rigging.",
    )

    assert ambiguous.applied is False
    assert ambiguous.output == "Pascal spoke to the crew."
    assert unconstrained.applied is False
    assert unconstrained.output == "The crew adjusted the rigging."
    assert unconstrained.candidate_count == 0


def test_v9_official_detective_configuration_is_source_aware():
    unit = MemoryAgentBenchDevelopmentUnit(
        unit_id="Long_Range_Understanding:0100:cd66eabd2f070a38",
        family="Long_Range_Understanding",
        source="detective_qa",
        row_index=100,
        context="not opened by this configuration test",
        row={},
    )

    config = _dataset_config(unit)

    assert config["sub_dataset"] == "detective_qa"
    assert config["generation_max_length"] == 2000
