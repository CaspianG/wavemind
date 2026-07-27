from __future__ import annotations

from datetime import datetime, timezone

import pytest

from benchmarks.crypto_bybit_capitulation_benchmark import (
    BAR_SECONDS,
    BybitInstrument,
    BybitKline,
    BybitOpenInterest,
    BybitPublicClient,
    HORIZONS,
    build_feature_rows,
    load_or_download_dataset,
    run_cross_exchange_benchmark,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow


def test_bybit_client_paginates_klines_and_open_interest() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def request(endpoint: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((endpoint, dict(params)))
        if endpoint == "kline":
            if int(params["end"]) >= 3000:
                rows = [
                    ["3000", "3", "4", "2", "3.5", "10", "35"],
                    ["2000", "2", "3", "1", "2.5", "10", "25"],
                ]
            else:
                rows = [["1000", "1", "2", "0.5", "1.5", "10", "15"]]
            return {"retCode": 0, "result": {"list": rows}}
        cursor = str(params.get("cursor", ""))
        if not cursor:
            rows = [
                {"timestamp": "3000", "openInterest": "30"},
                {"timestamp": "2000", "openInterest": "20"},
            ]
            next_cursor = "page-2"
        else:
            rows = [{"timestamp": "1000", "openInterest": "10"}]
            next_cursor = ""
        return {
            "retCode": 0,
            "result": {
                "list": rows,
                "nextPageCursor": next_cursor,
            },
        }

    client = BybitPublicClient(request_json=request, request_pause=0.0)
    klines = client.fetch_klines(
        "TESTUSDT",
        start_timestamp=1,
        end_timestamp=3,
    )
    open_interest = client.fetch_open_interest(
        "TESTUSDT",
        start_timestamp=1,
        end_timestamp=3,
    )

    assert [row.start_timestamp for row in klines] == [1, 2, 3]
    assert [row.timestamp for row in open_interest] == [1, 2, 3]
    assert any(params.get("cursor") == "page-2" for _, params in calls)


def test_build_feature_rows_is_causal_and_horizon_aware() -> None:
    start = _timestamp("2024-01-01")
    bars = tuple(
        BybitKline(
            start_timestamp=start + index * BAR_SECONDS,
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=10.0,
            turnover=1000.0,
        )
        for index in range(70)
    )
    open_interest = tuple(
        BybitOpenInterest(
            timestamp=start + index * BAR_SECONDS,
            open_interest=1000.0 - index,
        )
        for index in range(71)
    )
    rows_12h = build_feature_rows(
        [BybitInstrument("TESTUSDT", bars, open_interest)],
        horizon=3,
    )
    rows_24h = build_feature_rows(
        [BybitInstrument("TESTUSDT", bars, open_interest)],
        horizon=6,
    )

    assert rows_12h
    assert rows_24h
    assert rows_12h[0].timestamp == bars[12].start_timestamp + BAR_SECONDS
    assert rows_12h[0].target_timestamp == (
        bars[15].start_timestamp + BAR_SECONDS
    )
    assert rows_24h[0].target_timestamp == (
        bars[18].start_timestamp + BAR_SECONDS
    )
    assert rows_24h[0].features["oi_change_1"] < 0.0
    expected = (bars[18].close / bars[12].close - 1.0) * 10_000.0
    assert rows_24h[0].future_return_bps == pytest.approx(expected)


def test_cross_exchange_benchmark_keeps_frozen_configuration() -> None:
    rows_by_horizon = {
        label: _synthetic_rows()
        for label in HORIZONS
    }
    payload = run_cross_exchange_benchmark(
        rows_by_horizon,
        symbols=("AAAUSDT", "BBBUSDT"),
        provenance={"dataset_sha256": "abc"},
    )

    assert payload["frozen_config"] == {
        "return_quantile": 0.01,
        "oi_quantile": 0.1,
        "confirmation": "decelerating_selloff",
    }
    assert set(payload["horizons"]) == set(HORIZONS)
    assert payload["symbols"] == ["AAAUSDT", "BBBUSDT"]


def test_dataset_download_resumes_a_matching_partial_cache(tmp_path) -> None:
    instruments = {
        symbol: _small_instrument(symbol)
        for symbol in ("AAAUSDT", "BBBUSDT")
    }

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch_instrument(
            self,
            symbol: str,
            *,
            start_timestamp: int,
            end_timestamp: int,
        ) -> BybitInstrument:
            del start_timestamp, end_timestamp
            self.calls.append(symbol)
            return instruments[symbol]

    first_client = RecordingClient()
    first, _ = load_or_download_dataset(
        ("AAAUSDT",),
        cache_path=tmp_path / "one.json.gz",
        client=first_client,  # type: ignore[arg-type]
    )
    assert [row.symbol for row in first] == ["AAAUSDT"]

    combined_cache = tmp_path / "combined.json.gz"
    combined_cache.write_bytes((tmp_path / "one.json.gz").read_bytes())
    import gzip
    import json

    with gzip.open(combined_cache, "rt", encoding="utf-8") as source:
        payload = json.load(source)
    payload["symbols"] = ["AAAUSDT", "BBBUSDT"]
    with gzip.open(combined_cache, "wt", encoding="utf-8") as sink:
        json.dump(payload, sink)

    second_client = RecordingClient()
    combined, _ = load_or_download_dataset(
        ("AAAUSDT", "BBBUSDT"),
        cache_path=combined_cache,
        client=second_client,  # type: ignore[arg-type]
    )
    assert second_client.calls == ["BBBUSDT"]
    assert [row.symbol for row in combined] == ["AAAUSDT", "BBBUSDT"]


def _synthetic_rows() -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    start = _timestamp("2023-01-01")
    end = _timestamp("2026-07-27")
    timestamp = start
    index = 0
    while timestamp < end:
        for symbol_index, symbol in enumerate(("AAAUSDT", "BBBUSDT")):
            is_event = index % 17 == symbol_index
            return_12 = -1000.0 if is_event else float(index % 100)
            oi_change = -500.0 if is_event else float(index % 80)
            rows.append(
                FeatureRow(
                    symbol=symbol,
                    timestamp=timestamp,
                    target_timestamp=timestamp + 24 * 60 * 60,
                    fold_index=-1,
                    features={
                        "return_1": -10.0,
                        "return_3": -90.0 if is_event else 30.0,
                        "return_12": return_12,
                        "oi_change_1": oi_change,
                        "taker_imbalance": 0.0,
                    },
                    future_return_bps=100.0 if is_event else -100.0,
                )
            )
        timestamp += 24 * 60 * 60
        index += 1
    return rows


def _small_instrument(symbol: str) -> BybitInstrument:
    start = _timestamp("2024-01-01")
    return BybitInstrument(
        symbol=symbol,
        klines=tuple(
            BybitKline(
                start_timestamp=start + index * BAR_SECONDS,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=10.0,
                turnover=1000.0,
            )
            for index in range(100)
        ),
        open_interest=tuple(
            BybitOpenInterest(
                timestamp=start + index * BAR_SECONDS,
                open_interest=1000.0,
            )
            for index in range(100)
        ),
    )


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
