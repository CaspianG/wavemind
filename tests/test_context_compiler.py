from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from wavemind import MemoryContextCompiler, MemoryContextPolicy


@dataclass
class Result:
    id: int
    text: str
    score: float
    namespace: str = "agent"
    tags: tuple[str, ...] = ("trajectory-state",)
    metadata: dict = field(default_factory=dict)


def test_context_compiler_enforces_budget_and_preserves_provenance():
    results = [
        Result(
            id=index,
            text=(
                "Unrelated introduction. " * 120
                + f"\nStep {index}: click the Deploy button and verify health."
                + "\nUnrelated tail. " * 120
            ),
            score=1.0 - index / 10,
            metadata={
                "trajectory_id": "deploy-1",
                "source_memory_ids": [index * 10],
            },
        )
        for index in range(1, 7)
    ]
    packet = MemoryContextCompiler().compile(
        "which button deploys and verifies health?",
        results,
        token_budget=240,
        max_items=5,
    )

    assert packet.estimated_tokens <= 240
    assert packet.original_estimated_tokens > packet.estimated_tokens
    assert packet.token_saving > 0.5
    assert 1 <= len(packet.items) <= 5
    assert packet.omitted_count >= 1
    assert "Deploy button" in packet.items[0].text
    assert packet.items[0].citation == "memory:1"
    assert packet.items[0].provenance == {
        "namespace": "agent",
        "tags": ["trajectory-state"],
        "source_memory_ids": [10],
        "trajectory_id": "deploy-1",
    }
    assert packet.as_dict()["schema"] == "wavemind.memory_context.v1"
    assert "memory:1" in packet.as_prompt()


def test_context_compiler_is_deterministic_and_keeps_short_text():
    results = [
        Result(id=1, text="Use the rollback command.", score=0.9),
        Result(id=2, text="Then verify service health.", score=0.8),
    ]
    compiler = MemoryContextCompiler()

    first = compiler.compile("rollback health", results)
    second = compiler.compile("rollback health", results)

    assert first == second
    assert [item.text for item in first.items] == [
        result.text for result in results
    ]
    assert first.token_saving == 0.0


def test_context_compiler_does_not_truncate_items_when_total_fits():
    first_text = " ".join(f"primary-{index}" for index in range(88))
    second_text = " ".join(f"secondary-{index}" for index in range(8))
    results = [
        Result(id=1, text=first_text, score=1.0),
        Result(id=2, text=second_text, score=0.9),
    ]

    packet = MemoryContextCompiler().compile(
        "primary",
        results,
        token_budget=120,
    )

    assert packet.estimated_tokens == 120
    assert [item.text for item in packet.items] == [first_text, second_text]
    assert all(item.truncated is False for item in packet.items)
    assert packet.policy["preserve_when_within_budget"] is True


def test_context_compiler_validates_inputs():
    with pytest.raises(ValueError, match="at least 32"):
        MemoryContextPolicy(default_token_budget=31)
    with pytest.raises(ValueError, match="must align"):
        MemoryContextCompiler().compile(
            "deploy",
            [Result(id=1, text="one", score=1.0)],
            texts=[],
        )
    with pytest.raises(ValueError, match="must not be empty"):
        MemoryContextCompiler().compile(
            " ",
            [Result(id=1, text="one", score=1.0)],
        )
