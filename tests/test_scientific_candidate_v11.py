from __future__ import annotations

from wavemind.scientific_answer_transducer import (
    canonicalize_evidence_contracted_answer,
)


LIST_QUERY = (
    "Choose the next event from "
    "['Pascal instructed the team to adjust the rigging.', "
    "'Pascal ordered the crew to take in sail.', "
    "'Pascal commanded the crew to secure the cargo.']"
)

A_D_QUERY = """Now Answer the Question: What happened?
A. first event
B. second event
C. third event
D. fourth event
Output:
"""


def test_v11_unique_evidence_contract_overrides_unconstrained_paraphrase():
    result = canonicalize_evidence_contracted_answer(
        LIST_QUERY,
        "Pascal commanded everyone to lower the sails.",
        ("The pilot spoke. Pascal ordered the crew to take in sail.",),
    )

    assert result.applied is True
    assert result.output == "Pascal ordered the crew to take in sail."
    assert result.candidate_count == 3


def test_v11_retains_v10_strict_json_contract_for_a_d_questions():
    result = canonicalize_evidence_contracted_answer(
        A_D_QUERY,
        '{"answer":"C. third event","reasoning":"visible evidence"}',
        ("The third event occurred.",),
    )

    assert result.applied is True
    assert result.output == "C. third event"


def test_v11_ambiguous_evidence_falls_back_to_conservative_paraphrase():
    result = canonicalize_evidence_contracted_answer(
        LIST_QUERY,
        "Pascal commanded the crew to take in sail.",
        (
            "Pascal instructed the team to adjust the rigging. "
            "Pascal ordered the crew to take in sail.",
        ),
    )

    assert result.applied is True
    assert result.output == "Pascal ordered the crew to take in sail."
