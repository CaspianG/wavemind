from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


def _stamp(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def test_fred_parser_applies_publication_lag_and_skips_missing() -> None:
    from benchmarks.crypto_fred_macro import parse_fred_csv

    rows = parse_fred_csv(
        b"observation_date,VIXCLS\n2026-01-01,20.0\n2026-01-02,.\n",
        series="VIXCLS",
        publication_lag_days=2,
    )

    assert len(rows) == 1
    assert rows[0].available_timestamp == _stamp(date(2026, 1, 3))


def test_fred_dataset_round_trip(tmp_path: Path) -> None:
    from benchmarks.crypto_fred_macro import (
        FredDataset,
        FredObservation,
        load_fred_dataset,
        save_fred_dataset,
    )

    dataset = FredDataset(
        "2026-01-01",
        "2026-01-02",
        2,
        (FredObservation("VIXCLS", "2026-01-01", 123, 20.0),),
        ("url",),
        ("a" * 64,),
    )
    path = tmp_path / "fred.json.gz"
    save_fred_dataset(path, dataset)

    assert load_fred_dataset(path) == dataset


def test_fred_features_use_only_available_observations() -> None:
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow
    from benchmarks.crypto_fred_macro import (
        FRED_SERIES,
        FredDataset,
        FredObservation,
        add_fred_macro_features,
    )

    start = date(2025, 1, 1)
    observations = []
    for series_index, series in enumerate(FRED_SERIES):
        for offset in range(61):
            observed = start + timedelta(days=offset)
            observations.append(
                FredObservation(
                    series,
                    observed.isoformat(),
                    _stamp(observed + timedelta(days=2)),
                    100.0
                    + series_index
                    + offset
                    + (20.0 if offset == 60 else 0.0),
                )
            )
    dataset = FredDataset("", "", 2, tuple(observations), (), ())
    before_last = FeatureRow(
        "BTCUSDT",
        _stamp(start + timedelta(days=61)),
        0,
        0,
        {},
        1.0,
    )
    after_last = FeatureRow(
        "BTCUSDT",
        _stamp(start + timedelta(days=62)),
        0,
        0,
        {},
        1.0,
    )
    stale = FeatureRow(
        "BTCUSDT",
        _stamp(start + timedelta(days=80)),
        0,
        0,
        {},
        1.0,
    )

    enriched = add_fred_macro_features(
        [before_last, after_last, stale],
        dataset,
        min_history=60,
    )

    assert len(enriched) == 2
    assert enriched[0].features["fred_vixcls_z60"] != enriched[1].features[
        "fred_vixcls_z60"
    ]
    assert enriched[1].features["fred_max_age_days"] == 0.0


def test_fred_feature_validation_is_strict() -> None:
    from benchmarks.crypto_fred_macro import FredDataset, add_fred_macro_features

    empty = FredDataset("", "", 2, (), (), ())
    with pytest.raises(ValueError, match="at least 20"):
        add_fred_macro_features([], empty, min_history=19)
    with pytest.raises(ValueError, match="max_age_days"):
        add_fred_macro_features([], empty, max_age_days=0)
