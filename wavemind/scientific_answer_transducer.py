from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from typing import Sequence

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


_FINAL_QUESTION_MARKER = "Now Answer the Question:"
_LABELED_OPTION_RE = re.compile(r"(?m)^\s*([A-D])[.)]\s*(\S.*)\s*$")
_DIRECT_LABEL_RE = re.compile(r"^\s*([A-D])(?:[.)](?:\s|$)|\s)")


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


def canonicalize_strict_multiple_choice_answer(
    query: str,
    model_output: str,
) -> AnswerTransduction:
    """Decode an explicit A-D answer without consulting any gold field.

    Only options after the final benchmark question marker are eligible.  The
    output is changed only when a JSON ``answer`` string or a direct answer
    identifies one of those options by label or exact normalized text.
    """

    raw_output = str(model_output)
    question_scope = str(query).rsplit(_FINAL_QUESTION_MARKER, 1)
    if len(question_scope) != 2:
        return AnswerTransduction(raw_output, False, 0.0, 0.0, 0)
    options: dict[str, str] = {}
    for match in _LABELED_OPTION_RE.finditer(question_scope[1]):
        label = match.group(1)
        option_text = match.group(2).strip()
        if label not in options:
            options[label] = f"{label}. {option_text}"
    if not options:
        return AnswerTransduction(raw_output, False, 0.0, 0.0, 0)

    candidate = raw_output.strip()
    try:
        decoded = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("answer"), str):
        candidate = decoded["answer"].strip()

    label_match = _DIRECT_LABEL_RE.match(candidate)
    if label_match and label_match.group(1) in options:
        return AnswerTransduction(
            options[label_match.group(1)], True, 1.0, 1.0, len(options)
        )

    normalized_candidate = normalize_query_phrase(candidate)
    for label, option in options.items():
        option_text = option.split(". ", 1)[1]
        if normalized_candidate == normalize_query_phrase(option_text):
            return AnswerTransduction(option, True, 1.0, 1.0, len(options))
        if normalized_candidate == normalize_query_phrase(option):
            return AnswerTransduction(options[label], True, 1.0, 1.0, len(options))
    return AnswerTransduction(raw_output, False, 0.0, 0.0, len(options))


def canonicalize_evidence_contracted_answer(
    query: str,
    model_output: str,
    evidence_contents: Sequence[str],
) -> AnswerTransduction:
    """Resolve query contracts using only treatment-visible evidence.

    Explicit A-D answers remain strict. For list-style options, a unique exact
    occurrence in retrieved evidence is authoritative; otherwise the existing
    conservative paraphrase projection is used. Gold and scorer fields are not
    accepted by this interface.
    """

    strict = canonicalize_strict_multiple_choice_answer(query, model_output)
    if strict.applied:
        return strict

    options = extract_query_candidate_options(query)
    normalized_evidence = tuple(
        normalize_query_phrase(content) for content in evidence_contents
    )
    if options and normalized_evidence:
        scored = []
        for index, option in enumerate(options):
            normalized_option = normalize_query_phrase(option)
            occurrence_count = sum(
                content.count(normalized_option)
                for content in normalized_evidence
                if normalized_option
            )
            scored.append((occurrence_count, index, option))
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_count, _, best_option = scored[0]
        runner_up_count = scored[1][0] if len(scored) > 1 else 0
        if best_count > 0 and best_count > runner_up_count:
            return AnswerTransduction(
                best_option,
                True,
                1.0,
                (best_count - runner_up_count) / best_count,
                len(options),
            )

    return canonicalize_query_constrained_answer(query, model_output)
