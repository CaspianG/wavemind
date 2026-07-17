import sys
import types

import pytest


def test_derivatives_csv_round_trip(tmp_path):
    from benchmarks.crypto_derivatives import (
        DerivativesObservation,
        load_derivatives_csv,
        save_derivatives_csv,
    )

    path = tmp_path / "market" / "derivatives.csv"
    original = [
        DerivativesObservation(timestamp=2, open_interest_value=1200.0),
        DerivativesObservation(timestamp=1, funding_rate=0.0001, long_short_ratio=1.2),
    ]

    save_derivatives_csv(path, original)
    loaded = load_derivatives_csv(path)

    assert [row.timestamp for row in loaded] == [1, 2]
    assert loaded[0].funding_rate == pytest.approx(0.0001)
    assert loaded[1].funding_rate is None


def test_causal_alignment_never_uses_future_observation():
    from benchmarks.crypto_derivatives import DerivativesObservation, align_derivatives_to_bars
    from benchmarks.crypto_ohlcv import OHLCVBar

    bars = [
        OHLCVBar(timestamp=0, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0),
        OHLCVBar(timestamp=3600, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0),
    ]
    observations = [
        DerivativesObservation(
            timestamp=3500,
            funding_rate=0.001,
            open_interest_value=100.0,
            long_short_ratio=1.1,
        ),
        DerivativesObservation(
            timestamp=3700,
            funding_rate=0.009,
            open_interest_value=999.0,
            long_short_ratio=9.9,
        ),
    ]

    aligned = align_derivatives_to_bars(bars, observations, timeframe="1h")

    assert aligned[0].observed_until_ts == 3600
    assert aligned[0].funding_rate == pytest.approx(0.001)
    assert aligned[0].funding_timestamp == 3500
    assert aligned[1].observed_until_ts == 7200
    assert aligned[1].funding_rate == pytest.approx(0.009)


def test_causal_alignment_fails_closed_on_missing_or_stale_streams():
    from benchmarks.crypto_derivatives import DerivativesObservation, align_derivatives_to_bars
    from benchmarks.crypto_ohlcv import OHLCVBar

    bar = OHLCVBar(timestamp=3600, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)
    incomplete = [DerivativesObservation(timestamp=1000, funding_rate=0.001)]

    with pytest.raises(ValueError, match="No causal derivatives state"):
        align_derivatives_to_bars([bar], incomplete, timeframe="1h")

    complete = [
        DerivativesObservation(
            timestamp=1000,
            funding_rate=0.001,
            open_interest_value=100.0,
            long_short_ratio=1.1,
        )
    ]
    with pytest.raises(ValueError, match="Stale derivatives state"):
        align_derivatives_to_bars([bar], complete, timeframe="1h", max_age_seconds=3600)


def test_fetch_derivatives_ccxt_normalizes_and_paginates(monkeypatch):
    from benchmarks.crypto_derivatives import fetch_derivatives_ccxt

    calls = []

    class FakeExchange:
        def __init__(self, config):
            self.config = config
            self.has = {
                "fetchFundingRateHistory": True,
                "fetchOpenInterestHistory": True,
                "fetchLongShortRatioHistory": True,
            }

        def _rows(self, kind, since, limit):
            calls.append((kind, since, limit))
            base = int(since or 1_000_000)
            return [
                {
                    "timestamp": base + index * 3_600_000,
                    {
                        "funding": "fundingRate",
                        "oi": "openInterestValue",
                        "ratio": "longShortRatio",
                    }[kind]: 0.1 + index,
                }
                for index in range(limit)
            ]

        def fetch_funding_rate_history(self, *, symbol, since, limit, params):
            return self._rows("funding", since, limit)

        def fetch_open_interest_history(self, *, symbol, timeframe, since, limit, params):
            assert timeframe == "1h"
            return self._rows("oi", since, limit)

        def fetch_long_short_ratio_history(self, *, symbol, timeframe, since, limit, params):
            assert timeframe == "1h"
            return self._rows("ratio", since, limit)

    monkeypatch.setitem(sys.modules, "ccxt", types.SimpleNamespace(okx=FakeExchange))

    rows = fetch_derivatives_ccxt(
        exchange_id="okx",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=1_700_000_000,
        limit=105,
    )

    assert len(rows) == 105
    assert rows[0].funding_rate == pytest.approx(0.1)
    assert rows[0].open_interest_value == pytest.approx(0.1)
    assert rows[0].long_short_ratio == pytest.approx(0.1)
    assert any(call[2] == 5 for call in calls)


def test_fetch_derivatives_ccxt_refuses_missing_stream(monkeypatch):
    from benchmarks.crypto_derivatives import fetch_derivatives_ccxt

    class FakeExchange:
        def __init__(self, config):
            self.has = {
                "fetchFundingRateHistory": True,
                "fetchOpenInterestHistory": False,
                "fetchLongShortRatioHistory": True,
            }

    monkeypatch.setitem(sys.modules, "ccxt", types.SimpleNamespace(okx=FakeExchange))

    with pytest.raises(RuntimeError, match="fetchOpenInterestHistory"):
        fetch_derivatives_ccxt(exchange_id="okx", symbol="BTC/USDT:USDT")
