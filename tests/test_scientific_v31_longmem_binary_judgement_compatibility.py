from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_LONGMEM = ROOT.parents[1] / "scientific-evidence" / "upstreams" / "longmemeval-v2"


def _load_runner():
    backend = types.ModuleType("scientific_longmemeval_v2_backend")
    backend.CANDIDATE_SOURCE_SHA = "candidate"
    backend.MEMORY_TYPE = "memory"
    backend.OFFICIAL_REPOSITORY_SHA = "official"
    backend.register_backend = lambda **_: None
    backend.registration_fingerprint = lambda: "fingerprint"
    sys.modules[backend.__name__] = backend
    spec = importlib.util.spec_from_file_location(
        "test_scientific_longmemeval_v31_binary_compatibility_runner",
        ROOT / "benchmarks" / "scientific_longmemeval_v2_run.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_metrics_module():
    module = types.SimpleNamespace()

    def original(text: str):
        if text == '{"label": 1, "reason": "canonical"}':
            return 1, "canonical"
        raise ValueError(f"unparseable: {text!r}")

    module._parse_llm_binary_judgement = original
    module._stringify_text = str
    module._strip_markdown_code_fence = lambda text: text.strip()
    return module, original


def test_binary_compatibility_attempts_frozen_parser_first():
    runner = _load_runner()
    metrics, original = _fake_metrics_module()
    runner._install_binary_judgement_compatibility(metrics)

    assert metrics._parse_llm_binary_judgement(
        '{"label": 1, "reason": "canonical"}'
    ) == (1, "canonical")
    assert metrics._parse_llm_binary_judgement is not original


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('1, reason: "unambiguous positive"', 1),
        ("0, reason: unambiguous negative", 0),
        ("  1 , ReAsOn : explanation across\nlines  ", 1),
    ],
)
def test_binary_compatibility_accepts_only_leading_label_reason_shape(text, expected):
    runner = _load_runner()
    metrics, _ = _fake_metrics_module()
    runner._install_binary_judgement_compatibility(metrics)

    label, reason = metrics._parse_llm_binary_judgement(text)

    assert label == expected
    assert reason == text.strip()


@pytest.mark.parametrize(
    "text",
    [
        "1",
        "reason: positive",
        "maybe 1, reason: ambiguous prefix",
        "1, reason:",
        "2, reason: invalid label",
        "1, rationale: wrong field",
    ],
)
def test_binary_compatibility_keeps_ambiguous_or_unlabelled_text_invalid(text):
    runner = _load_runner()
    metrics, _ = _fake_metrics_module()
    runner._install_binary_judgement_compatibility(metrics)

    with pytest.raises(ValueError):
        metrics._parse_llm_binary_judgement(text)


def test_binary_compatibility_install_is_idempotent():
    runner = _load_runner()
    metrics, _ = _fake_metrics_module()
    runner._install_binary_judgement_compatibility(metrics)
    installed = metrics._parse_llm_binary_judgement
    runner._install_binary_judgement_compatibility(metrics)

    assert metrics._parse_llm_binary_judgement is installed


def test_binary_compatibility_wraps_exact_official_parser_without_changing_existing_forms():
    runner = _load_runner()
    sys.path.insert(0, str(OFFICIAL_LONGMEM))
    try:
        from evaluation import qa_eval_metrics

        original = qa_eval_metrics._parse_llm_binary_judgement
        canonical = '{"label": 1, "reason": "canonical"}'
        expected = original(canonical)
        runner._install_binary_judgement_compatibility(qa_eval_metrics)

        assert qa_eval_metrics._parse_llm_binary_judgement(canonical) == expected
        assert qa_eval_metrics._parse_llm_binary_judgement(
            '1, reason: "the frozen judge supplied an explicit label"'
        )[0] == 1
        with pytest.raises(ValueError):
            qa_eval_metrics._parse_llm_binary_judgement("ambiguous judgement")
    finally:
        if "qa_eval_metrics" in locals():
            qa_eval_metrics._parse_llm_binary_judgement = original
        sys.path.remove(str(OFFICIAL_LONGMEM))
