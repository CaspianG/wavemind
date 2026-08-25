from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .scientific_query_phrases import (
    extract_query_candidate_options,
    normalize_query_phrase,
)


@dataclass(frozen=True)
class AnswerTransduction:
    output: str
    applied: bool
    similarity: float
    winner_margin: float
    candidate_count: int


def _token_multiset_f1(left: str, right: str) -> float:
    left_tokens = Counter(normalize_query_phrase(left).split())
    right_tokens = Counter(normalize_query_phrase(right).split())
    overlap = sum((left_tokens & right_tokens).values())
    if not overlap:
        return 0.0
    precision = overlap / sum(left_tokens.values())
    recall = overlap / sum(right_tokens.values())
    return 2.0 * precision * recall / (precision + recall)


def canonicalize_query_constrained_answer(
    query: str,
    model_output: str,
    *,
    minimum_similarity: float = 0.5,
    minimum_winner_margin: float = 0.1,
) -> AnswerTransduction:
    """Project a sufficiently clear treatment answer to a query-provided option."""

    options = extract_query_candidate_options(query)
    if not options:
        return AnswerTransduction(str(model_output), False, 0.0, 0.0, 0)
    scored = sorted(
        (
            (_token_multiset_f1(model_output, option), index, option)
            for index, option in enumerate(options)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    best_score, _, best_option = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = best_score - runner_up_score
    applied = best_score >= minimum_similarity and margin >= minimum_winner_margin
    return AnswerTransduction(
        best_option if applied else str(model_output),
        applied,
        best_score,
        margin,
        len(options),
    )
