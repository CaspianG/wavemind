import pytest


def test_load_ohlcv_csv_case_insensitive_and_sorted(tmp_path):
    from benchmarks.crypto_ohlcv import load_ohlcv_csv

    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "\n".join(
            [
                "TimeStamp,Open,High,Low,Close,Volume",
                "2024-01-01T02:00:00Z,102,104,101,103,12",
                "2024-01-01T00:00:00Z,100,101,99,100.5,10",
                "2024-01-01T01:00:00Z,100.5,102,100,102,11",
            ]
        ),
        encoding="utf-8",
    )

    bars = load_ohlcv_csv(csv_path)

    assert [bar.close for bar in bars] == [100.5, 102.0, 103.0]
    assert bars[0].timestamp < bars[-1].timestamp


def test_generate_synthetic_ohlcv_and_windows_have_no_query_leakage():
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows, window_to_text

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="1h", bars=80, seed=1)
    windows = make_ohlcv_windows(bars, symbol="BTC", timeframe="1h", window=16, horizon=4)

    assert len(windows) == 61
    assert windows[0].future_end_ts > windows[0].end_ts
    assert {"up", "down", "flat"} & {window.direction for window in windows}
    assert "future_return_bps" not in window_to_text(windows[0], include_outcome=False)
    assert "future_return_bps" in window_to_text(windows[0], include_outcome=True)


def test_make_ohlcv_windows_requires_enough_bars():
    from benchmarks.crypto_ohlcv import generate_synthetic_ohlcv, make_ohlcv_windows

    bars = generate_synthetic_ohlcv(symbol="BTC", timeframe="1h", bars=10, seed=1)

    with pytest.raises(ValueError, match="not enough bars"):
        make_ohlcv_windows(bars, symbol="BTC", timeframe="1h", window=16, horizon=4)
