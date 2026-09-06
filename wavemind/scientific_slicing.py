from __future__ import annotations

import re


V7_SLICE_CHARACTERS = 1024
V7_SLICE_OVERLAP = 256
_WHITESPACE_RE = re.compile(r"\s+")


def slice_candidate_content(
    content: str,
    *,
    maximum_characters: int = V7_SLICE_CHARACTERS,
    overlap_characters: int = V7_SLICE_OVERLAP,
) -> tuple[tuple[str, int], ...]:
    """Create deterministic, whitespace-aligned overlapping evidence slices."""

    if maximum_characters < 1 or not 0 <= overlap_characters < maximum_characters:
        raise ValueError("candidate slice bounds are invalid")
    normalized = _WHITESPACE_RE.sub(" ", str(content)).strip()
    if not normalized:
        return ()
    slices: list[tuple[str, int]] = []
    start = 0
    while start < len(normalized):
        hard_end = min(len(normalized), start + maximum_characters)
        end = hard_end
        if hard_end < len(normalized):
            boundary = normalized.rfind(" ", max(start + 1, hard_end - 128), hard_end)
            if boundary > start:
                end = boundary
        value = normalized[start:end].strip()
        if value:
            slices.append((value, start))
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap_characters)
    return tuple(slices)
