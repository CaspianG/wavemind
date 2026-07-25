from __future__ import annotations

from datetime import datetime, timezone


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def _payload(days: int = 10):
    from benchmarks.crypto_coinmetrics_onchain import COINMETRICS_METRICS

    rows = []
    for asset_index, asset in enumerate(("btc", "eth")):
        for day in range(days):
            row = {
                "asset": asset,
                "time": f"2026-01-{day + 1:02d}T00:00:00.000000000Z",
            }
            row.update(
                {
                    metric: str(1000.0 + asset_index * 100.0 + day + index)
                    for index, metric in enumerate(COINMETRICS_METRICS)
                }
            )
            rows.append(row)
    return {"data": rows}


def test_onchain_parser_applies_publication_lag():
    from benchmarks.crypto_coinmetrics_onchain import (
        COINMETRICS_METRICS,
        parse_onchain_payload,
    )

    observations = parse_onchain_payload(
        _payload(2),
        metrics=COINMETRICS_METRICS,
        publication_lag_days=2,
    )

    assert len(observations) == 4
    assert observations[0].available_timestamp == _timestamp(
        "2026-01-03T00:00:00"
    )


def test_onchain_parser_prefers_source_completion_timestamp():
    from benchmarks.crypto_coinmetrics_onchain import (
        COINMETRICS_METRICS,
        COMPLETION_METRIC,
        parse_onchain_payload,
    )

    payload = _payload(1)
    expected = _timestamp("2026-01-02T03:15:00")
    payload["data"][0][COMPLETION_METRIC] = str(expected)
    payload["data"][0]["FlowInExUSD-status-time"] = (
        "2026-01-02T03:10:00.000000000Z"
    )

    observations = parse_onchain_payload(
        payload,
        metrics=COINMETRICS_METRICS,
        publication_lag_days=2,
    )

    assert observations[0].available_timestamp == expected


def test_onchain_parser_rejects_late_recomputation_timestamp():
    from benchmarks.crypto_coinmetrics_onchain import (
        COINMETRICS_METRICS,
        COMPLETION_METRIC,
        parse_onchain_payload,
    )

    payload = _payload(1)
    payload["data"][0][COMPLETION_METRIC] = str(
        _timestamp("2026-06-01T03:15:00")
    )

    observations = parse_onchain_payload(
        payload,
        metrics=COINMETRICS_METRICS,
        publication_lag_days=2,
    )

    assert observations[0].available_timestamp == _timestamp(
        "2026-01-03T00:00:00"
    )


def test_onchain_features_never_use_future_observation():
    from benchmarks.crypto_coinmetrics_onchain import (
        COINMETRICS_METRICS,
        OnChainDataset,
        add_onchain_features,
        parse_onchain_payload,
    )
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    observations = parse_onchain_payload(
        _payload(10),
        metrics=COINMETRICS_METRICS,
        publication_lag_days=2,
    )
    dataset = OnChainDataset(
        start_date="2026-01-01",
        end_date="2026-01-10",
        publication_lag_days=2,
        observations=tuple(observations),
        source_urls=("https://example.test/data",),
        source_sha256=("a" * 64,),
    )
    before = FeatureRow(
        symbol="BTCUSDT",
        timestamp=_timestamp("2026-01-09T23:59:59"),
        target_timestamp=_timestamp("2026-01-10T23:59:59"),
        fold_index=0,
        features={},
        future_return_bps=10.0,
    )
    after = FeatureRow(
        symbol="BTCUSDT",
        timestamp=_timestamp("2026-01-10T00:00:00"),
        target_timestamp=_timestamp("2026-01-11T00:00:00"),
        fold_index=0,
        features={},
        future_return_bps=10.0,
    )

    before_features = add_onchain_features(
        [before], dataset, min_history=7
    )[0].features
    after_features = add_onchain_features(
        [after], dataset, min_history=7
    )[0].features

    assert before_features["cm_adractcnt_z60"] != after_features["cm_adractcnt_z60"]
    assert before_features["cm_max_age_days"] > after_features["cm_max_age_days"]


def test_onchain_dataset_round_trip(tmp_path):
    from benchmarks.crypto_coinmetrics_onchain import (
        COINMETRICS_METRICS,
        OnChainDataset,
        load_onchain_dataset,
        parse_onchain_payload,
        save_onchain_dataset,
    )

    dataset = OnChainDataset(
        start_date="2026-01-01",
        end_date="2026-01-02",
        publication_lag_days=2,
        observations=tuple(
            parse_onchain_payload(
                _payload(2),
                metrics=COINMETRICS_METRICS,
                publication_lag_days=2,
            )
        ),
        source_urls=("https://example.test/data",),
        source_sha256=("b" * 64,),
    )
    path = tmp_path / "onchain.json.gz"

    save_onchain_dataset(path, dataset)
    restored = load_onchain_dataset(path)

    assert restored == dataset
