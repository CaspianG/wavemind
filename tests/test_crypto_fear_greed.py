from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _payload(rows: list[dict[str, str]]) -> bytes:
    return json.dumps(
        {
            "name": "Fear and Greed Index",
            "data": rows,
            "metadata": {"error": None},
        }
    ).encode()


def test_parser_applies_conservative_publication_lag() -> None:
    from benchmarks.crypto_fear_greed import parse_fear_greed_json

    rows = parse_fear_greed_json(
        _payload(
            [
                {
                    "value": "25",
                    "value_classification": "Extreme Fear",
                    "timestamp": "1",
                }
            ]
        ),
        publication_lag_hours=24,
    )

    assert len(rows) == 1
    assert rows[0].observation_timestamp == 1
    assert rows[0].available_timestamp == 86_401


def test_parser_rejects_invalid_response_and_lag() -> None:
    from benchmarks.crypto_fear_greed import parse_fear_greed_json

    with pytest.raises(ValueError, match="at least one"):
        parse_fear_greed_json(_payload([]), publication_lag_hours=0)
    with pytest.raises(ValueError, match="response shape"):
        parse_fear_greed_json(b"{}", publication_lag_hours=24)


def test_dataset_round_trip(tmp_path: Path) -> None:
    from benchmarks.crypto_fear_greed import (
        FearGreedDataset,
        FearGreedObservation,
        load_fear_greed_dataset,
        save_fear_greed_dataset,
    )

    dataset = FearGreedDataset(
        publication_lag_hours=24,
        observations=(FearGreedObservation(1, 2, 30.0, "Fear"),),
        source_url="https://example.test/fng",
        source_sha256="a" * 64,
    )
    path = tmp_path / "fng.json.gz"
    save_fear_greed_dataset(path, dataset)

    assert load_fear_greed_dataset(path) == dataset


def test_downloader_fingerprints_exact_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from benchmarks import crypto_fear_greed

    content = _payload(
        [
            {
                "value": "55",
                "value_classification": "Greed",
                "timestamp": "10",
            }
        ]
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return content

    monkeypatch.setattr(
        crypto_fear_greed.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    dataset = crypto_fear_greed.download_fear_greed_dataset()

    assert dataset.source_sha256 == hashlib.sha256(content).hexdigest()
    assert dataset.observations[0].available_timestamp == 86_410


def test_features_never_see_future_observation() -> None:
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
    from benchmarks.crypto_fear_greed import (
        FearGreedDataset,
        FearGreedObservation,
        add_fear_greed_features,
    )

    observations = tuple(
        FearGreedObservation(
            observation_timestamp=index * 86_400,
            available_timestamp=(index + 1) * 86_400,
            value=float(30 + index % 40),
            classification="",
        )
        for index in range(92)
    )
    dataset = FearGreedDataset(24, observations, "url", "a" * 64)
    current = FeatureRow(
        "BTCUSDT",
        91 * 86_400,
        0,
        0,
        {"return_6": 2.0, "return_36": 3.0},
        1.0,
    )
    after = FeatureRow(
        "BTCUSDT",
        92 * 86_400,
        0,
        0,
        {"return_6": 2.0, "return_36": 3.0},
        1.0,
    )

    enriched = add_fear_greed_features([current, after], dataset)

    assert len(enriched) == 2
    assert enriched[0].features["fng_value"] == pytest.approx(
        observations[90].value / 50.0 - 1.0
    )
    assert enriched[1].features["fng_value"] == pytest.approx(
        observations[91].value / 50.0 - 1.0
    )


def test_feature_validation_is_strict() -> None:
    from benchmarks.crypto_fear_greed import (
        FearGreedDataset,
        add_fear_greed_features,
    )

    empty = FearGreedDataset(24, (), "", "")
    with pytest.raises(ValueError, match="at least 30"):
        add_fear_greed_features([], empty, min_history=29)
    with pytest.raises(ValueError, match="max_age_hours"):
        add_fear_greed_features([], empty, max_age_hours=0)
