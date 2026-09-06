from __future__ import annotations

from wavemind.scientific_answer_transducer import (
    canonicalize_strict_multiple_choice_answer,
)


QUERY = """For example:
Question: Which example is right?
A. The old A
B. The old B
C. The old C
D. The old D

Now Answer the Question: Which character is related to the death?
A. Mrs. Hemm
B. Mr. and Mrs. MacNamara
C. The Brandt couple
D. Miss House
Output:
"""


def test_v10_strict_decoder_uses_only_final_query_options_and_json_answer():
    result = canonicalize_strict_multiple_choice_answer(
        QUERY,
        '{"answer":"C. The Brandt couple","reasoning":"memory evidence"}',
    )

    assert result.applied is True
    assert result.output == "C. The Brandt couple"
    assert result.candidate_count == 4


def test_v10_strict_decoder_accepts_direct_label_or_exact_option_text():
    direct = canonicalize_strict_multiple_choice_answer(QUERY, "D. Miss House")
    text_only = canonicalize_strict_multiple_choice_answer(QUERY, "Mrs. Hemm")

    assert direct.output == "D. Miss House"
    assert text_only.output == "A. Mrs. Hemm"
    assert direct.applied is text_only.applied is True


def test_v10_strict_decoder_fails_closed_without_a_valid_final_option():
    wrong = canonicalize_strict_multiple_choice_answer(
        QUERY,
        '{"answer":"Miss Watrous","reasoning":"unsupported"}',
    )
    missing_marker = canonicalize_strict_multiple_choice_answer(
        "A. one\nB. two",
        "A. one",
    )

    assert wrong.applied is False
    assert wrong.output.startswith('{"answer":"Miss Watrous"')
    assert missing_marker.applied is False
    assert missing_marker.candidate_count == 0
