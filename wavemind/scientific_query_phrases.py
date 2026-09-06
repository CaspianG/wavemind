from __future__ import annotations

import ast
import unicodedata


MAX_QUERY_LITERAL_CHARACTERS = 8192
MAX_QUERY_LITERAL_CANDIDATES = 64
MIN_DISTINCT_PHRASES = 2
MAX_DISTINCT_PHRASES = 20


def normalize_query_phrase(value: str) -> str:
    """Apply the frozen v8 phrase normalization without language heuristics."""

    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    separated = "".join(
        character if character.isalnum() else " " for character in normalized
    )
    return " ".join(separated.split())


def _literal_candidates(query: str):
    pairs = {"[": "]", "(": ")"}
    for start, opening in enumerate(query):
        closing = pairs.get(opening)
        if closing is None:
            continue
        quote = ""
        escaped = False
        depth = 0
        for end in range(start, min(len(query), start + MAX_QUERY_LITERAL_CHARACTERS)):
            character = query[end]
            if quote:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = ""
                continue
            if character in {"'", '"'}:
                quote = character
            elif character == opening:
                depth += 1
            elif character == closing:
                depth -= 1
                if depth == 0:
                    yield query[start : end + 1]
                    break


def extract_query_candidate_options(query: str) -> tuple[str, ...]:
    """Extract bounded raw string options already visible in a query."""

    options: list[str] = []
    seen: set[str] = set()
    for candidate_index, candidate in enumerate(_literal_candidates(str(query))):
        if candidate_index >= MAX_QUERY_LITERAL_CANDIDATES:
            break
        try:
            parsed = ast.literal_eval(candidate)
        except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
            continue
        if not isinstance(parsed, (list, tuple)) or not (2 <= len(parsed) <= 20):
            continue
        if not all(isinstance(item, str) for item in parsed):
            continue
        normalized = [normalize_query_phrase(item) for item in parsed]
        if any(len(item.split()) < 2 for item in normalized):
            continue
        for raw_item, normalized_item in zip(parsed, normalized):
            if normalized_item and normalized_item not in seen:
                seen.add(normalized_item)
                options.append(raw_item.strip())
                if len(options) >= MAX_DISTINCT_PHRASES:
                    break
        if len(options) >= MAX_DISTINCT_PHRASES:
            break
    if len(options) < MIN_DISTINCT_PHRASES:
        return ()
    return tuple(options)


def extract_query_candidate_phrases(query: str) -> tuple[str, ...]:
    """Return normalized forms of accepted query-provided string options."""

    return tuple(
        normalize_query_phrase(option)
        for option in extract_query_candidate_options(query)
    )
