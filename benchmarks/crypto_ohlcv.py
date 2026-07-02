from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np


TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


@dataclass(frozen=True)
class OHLCVBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class OHLCVWindow:
    id: str
    symbol: str
    timeframe: str
    index: int
    start_ts: int
    end_ts: int
    future_end_ts: int
    bars: tuple[OHLCVBar, ...]
    features: Mapping[str, float | str]
    future_return_bps: float
    max_favorable_excursion_bps: float
    max_adverse_excursion_bps: float
    future_realized_vol_bps: float
    future_max_drawdown_bps: float
    direction: str

    @property
    def start_time(self) -> str:
        return datetime.fromtimestamp(self.start_ts, tz=timezone.utc).isoformat()

    @property
    def end_time(self) -> str:
        return datetime.fromtimestamp(self.end_ts, tz=timezone.utc).isoformat()


def timeframe_to_seconds(timeframe: str) -> int:
    key = timeframe.strip().lower()
    if key not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe {timeframe!r}. Known: {', '.join(sorted(TIMEFRAME_SECONDS))}")
    return TIMEFRAME_SECONDS[key]


def parse_timestamp(value: Any) -> int:
    if value is None:
        raise ValueError("timestamp is required")
    raw = str(value).strip()
    if not raw:
        raise ValueError("timestamp is empty")
    try:
        number = float(raw)
    except ValueError:
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"Unsupported timestamp format: {raw!r}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    if number > 10_000_000_000:
        number = number / 1000.0
    return int(number)


def load_ohlcv_csv(
    path: str | Path,
    *,
    timestamp_col: str = "timestamp",
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
) -> list[OHLCVBar]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {csv_path}")
        columns = {name.strip().lower(): name for name in reader.fieldnames}

        def column(name: str) -> str:
            key = name.strip().lower()
            if key not in columns:
                raise ValueError(f"CSV {csv_path} is missing required column {name!r}")
            return columns[key]

        ts_key = column(timestamp_col)
        open_key = column(open_col)
        high_key = column(high_col)
        low_key = column(low_col)
        close_key = column(close_col)
        volume_key = column(volume_col)
        bars = [
            OHLCVBar(
                timestamp=parse_timestamp(row[ts_key]),
                open=float(row[open_key]),
                high=float(row[high_key]),
                low=float(row[low_key]),
                close=float(row[close_key]),
                volume=float(row[volume_key]),
            )
            for row in reader
            if row
        ]
    if not bars:
        raise ValueError(f"CSV has no OHLCV rows: {csv_path}")
    return sorted(bars, key=lambda item: item.timestamp)


def fetch_ohlcv_ccxt(
    *,
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since: int | None = None,
    limit: int = 1000,
    params: Mapping[str, Any] | None = None,
) -> list[OHLCVBar]:
    try:
        import ccxt  # type: ignore
    except ImportError as exc:
        raise RuntimeError('Install the crypto extra first: pip install -e ".[crypto]"') from exc
    if not hasattr(ccxt, exchange_id):
        raise ValueError(f"Unknown CCXT exchange: {exchange_id}")
    exchange_cls = getattr(ccxt, exchange_id)
    exchange = exchange_cls({"enableRateLimit": True})
    rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit, params=dict(params or {}))
    return [
        OHLCVBar(
            timestamp=int(row[0] // 1000),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
    ]


def generate_synthetic_ohlcv(
    *,
    symbol: str,
    timeframe: str,
    bars: int = 600,
    seed: int = 7,
) -> list[OHLCVBar]:
    if bars <= 0:
        raise ValueError("bars must be positive")
    seconds = timeframe_to_seconds(timeframe)
    symbol_key = symbol.upper().replace("/USDT", "").replace("USDT", "")
    base_price = {
        "BTC": 62_000.0,
        "ETH": 3_100.0,
        "SOL": 145.0,
    }.get(symbol_key, 100.0)
    base_volume = {
        "BTC": 1_200.0,
        "ETH": 8_500.0,
        "SOL": 55_000.0,
    }.get(symbol_key, 10_000.0)
    rng_seed = seed + sum(ord(char) for char in f"{symbol}:{timeframe}")
    rng = np.random.default_rng(rng_seed)
    start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    price = base_price
    result: list[OHLCVBar] = []
    for index in range(bars):
        regime = (index // 85) % 4
        regime_drift_bps = (5.0, -4.0, 1.0, 0.0)[regime]
        cycle_bps = math.sin(index / 9.0) * 16.0 + math.sin(index / 31.0) * 9.0
        shock_bps = float(rng.normal(0.0, 18.0 + regime * 4.0))
        return_bps = regime_drift_bps + cycle_bps + shock_bps
        open_price = price
        close_price = max(1e-9, open_price * (1.0 + return_bps / 10_000.0))
        wick_bps = abs(float(rng.normal(22.0, 9.0))) + abs(return_bps) * 0.18
        high_price = max(open_price, close_price) * (1.0 + wick_bps / 10_000.0)
        low_price = min(open_price, close_price) * (1.0 - wick_bps / 10_000.0)
        volume = max(
            1e-9,
            base_volume
            * (1.0 + abs(return_bps) / 130.0 + max(0.0, math.sin(index / 17.0)) * 0.35)
            * float(rng.lognormal(0.0, 0.12)),
        )
        result.append(
            OHLCVBar(
                timestamp=start + index * seconds,
                open=float(open_price),
                high=float(high_price),
                low=float(low_price),
                close=float(close_price),
                volume=float(volume),
            )
        )
        price = close_price
    return result


def make_ohlcv_windows(
    bars: Iterable[OHLCVBar],
    *,
    symbol: str,
    timeframe: str,
    window: int = 32,
    horizon: int = 6,
    stride: int = 1,
    direction_threshold_bps: float = 15.0,
) -> list[OHLCVWindow]:
    ordered = sorted(list(bars), key=lambda item: item.timestamp)
    if window <= 1:
        raise ValueError("window must be greater than 1")
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if stride <= 0:
        raise ValueError("stride must be positive")
    if len(ordered) < window + horizon:
        raise ValueError("not enough bars for the requested window and horizon")

    windows: list[OHLCVWindow] = []
    safe_symbol = symbol.replace("/", "")
    for start in range(0, len(ordered) - window - horizon + 1, stride):
        segment = tuple(ordered[start : start + window])
        future_segment = tuple(ordered[start + window : start + window + horizon])
        future_bar = future_segment[-1]
        current_close = segment[-1].close
        future_return_bps = _return_bps(current_close, future_bar.close)
        outcomes = _future_outcomes(current_close, future_segment)
        if future_return_bps > direction_threshold_bps:
            direction = "up"
        elif future_return_bps < -direction_threshold_bps:
            direction = "down"
        else:
            direction = "flat"
        features = _window_features(segment)
        windows.append(
            OHLCVWindow(
                id=f"{safe_symbol}_{timeframe}_{start:06d}",
                symbol=symbol,
                timeframe=timeframe,
                index=start,
                start_ts=segment[0].timestamp,
                end_ts=segment[-1].timestamp,
                future_end_ts=future_bar.timestamp,
                bars=segment,
                features=features,
                future_return_bps=float(future_return_bps),
                max_favorable_excursion_bps=float(outcomes["max_favorable_excursion_bps"]),
                max_adverse_excursion_bps=float(outcomes["max_adverse_excursion_bps"]),
                future_realized_vol_bps=float(outcomes["future_realized_vol_bps"]),
                future_max_drawdown_bps=float(outcomes["future_max_drawdown_bps"]),
                direction=direction,
            )
        )
    return windows


def window_to_text(window: OHLCVWindow, *, include_outcome: bool = False) -> str:
    features = window.features
    parts = [
        "asset crypto",
        f"symbol {window.symbol}",
        f"timeframe {window.timeframe}",
        f"trend {features['trend']}",
        f"recent_trend {features['recent_trend']}",
        f"rsi_bucket {features['rsi_bucket']}",
        f"volatility_bucket {features['volatility_bucket']}",
        f"volume_bucket {features['volume_bucket']}",
        f"close_position {features['close_position_bucket']}",
        f"window_return_bps {features['window_return_bps']:.1f}",
        f"recent_return_bps {features['recent_return_bps']:.1f}",
        f"range_bps {features['range_bps']:.1f}",
        f"volatility_bps {features['volatility_bps']:.1f}",
        f"drawdown_bps {features['drawdown_bps']:.1f}",
        f"trend_slope_bps {features['trend_slope_bps']:.1f}",
        f"macd_bps {features['macd_bps']:.1f}",
        f"bollinger_position {features['bollinger_position']:.2f}",
        f"range_compression {features['range_compression']:.2f}",
        f"volume_ratio {features['volume_ratio']:.2f}",
        f"rsi {features['rsi']:.1f}",
    ]
    if include_outcome:
        parts.extend(
            [
                f"future_direction {window.direction}",
                f"future_return_bps {window.future_return_bps:.1f}",
                f"future_mfe_bps {window.max_favorable_excursion_bps:.1f}",
                f"future_mae_bps {window.max_adverse_excursion_bps:.1f}",
                f"future_realized_vol_bps {window.future_realized_vol_bps:.1f}",
                f"future_max_drawdown_bps {window.future_max_drawdown_bps:.1f}",
            ]
        )
    return " | ".join(parts)


def _window_features(bars: tuple[OHLCVBar, ...]) -> dict[str, float | str]:
    closes = np.asarray([bar.close for bar in bars], dtype=np.float64)
    highs = np.asarray([bar.high for bar in bars], dtype=np.float64)
    lows = np.asarray([bar.low for bar in bars], dtype=np.float64)
    volumes = np.asarray([bar.volume for bar in bars], dtype=np.float64)
    returns = np.diff(closes) / np.maximum(closes[:-1], 1e-12) * 10_000.0
    window_return = _return_bps(float(closes[0]), float(closes[-1]))
    recent_start = closes[max(0, len(closes) - 6)]
    recent_return = _return_bps(float(recent_start), float(closes[-1]))
    range_bps = (float(np.max(highs)) - float(np.min(lows))) / max(float(closes[-1]), 1e-12) * 10_000.0
    volatility_bps = float(np.std(returns)) if len(returns) else 0.0
    volume_ratio = float(volumes[-1] / max(float(np.mean(volumes)), 1e-12))
    rsi = _rsi(closes)
    low = float(np.min(lows))
    high = float(np.max(highs))
    close_position = (float(closes[-1]) - low) / max(high - low, 1e-12)
    drawdown_bps = _max_drawdown_bps(closes)
    trend_slope_bps = _trend_slope_bps(closes)
    macd_bps = _macd_bps(closes)
    bollinger_position = _bollinger_position(closes)
    recent_high = float(np.max(highs[max(0, len(highs) - 8) :]))
    recent_low = float(np.min(lows[max(0, len(lows) - 8) :]))
    recent_range_bps = (recent_high - recent_low) / max(float(closes[-1]), 1e-12) * 10_000.0
    range_compression = recent_range_bps / max(range_bps, 1e-12)
    return {
        "window_return_bps": float(window_return),
        "recent_return_bps": float(recent_return),
        "range_bps": float(range_bps),
        "volatility_bps": float(volatility_bps),
        "drawdown_bps": float(drawdown_bps),
        "trend_slope_bps": float(trend_slope_bps),
        "macd_bps": float(macd_bps),
        "bollinger_position": float(bollinger_position),
        "range_compression": float(range_compression),
        "volume_ratio": float(volume_ratio),
        "rsi": float(rsi),
        "close_position": float(close_position),
        "trend": _direction_bucket(window_return, threshold=25.0),
        "recent_trend": _direction_bucket(recent_return, threshold=12.0),
        "rsi_bucket": _rsi_bucket(rsi),
        "volatility_bucket": _three_bucket(volatility_bps, low=12.0, high=38.0, labels=("low", "normal", "high")),
        "volume_bucket": _three_bucket(volume_ratio, low=0.85, high=1.25, labels=("quiet", "normal", "expanded")),
        "close_position_bucket": _three_bucket(close_position, low=0.33, high=0.66, labels=("near_low", "middle", "near_high")),
        "drawdown_bucket": _three_bucket(abs(drawdown_bps), low=60.0, high=180.0, labels=("shallow", "normal", "deep")),
        "macd_bucket": _direction_bucket(macd_bps, threshold=8.0),
        "bollinger_bucket": _three_bucket(bollinger_position, low=-0.75, high=0.75, labels=("lower_band", "middle", "upper_band")),
    }


def _return_bps(start_price: float, end_price: float) -> float:
    return (float(end_price) / max(float(start_price), 1e-12) - 1.0) * 10_000.0


def _future_outcomes(current_close: float, future_bars: tuple[OHLCVBar, ...]) -> dict[str, float]:
    future_highs = np.asarray([bar.high for bar in future_bars], dtype=np.float64)
    future_lows = np.asarray([bar.low for bar in future_bars], dtype=np.float64)
    future_closes = np.asarray([current_close, *[bar.close for bar in future_bars]], dtype=np.float64)
    max_favorable = _return_bps(current_close, float(np.max(future_highs)))
    max_adverse = _return_bps(current_close, float(np.min(future_lows)))
    return {
        "max_favorable_excursion_bps": float(max_favorable),
        "max_adverse_excursion_bps": float(max_adverse),
        "future_realized_vol_bps": _realized_vol_bps(future_closes),
        "future_max_drawdown_bps": _max_drawdown_bps(future_closes),
    }


def _realized_vol_bps(closes: np.ndarray) -> float:
    if len(closes) < 2:
        return 0.0
    returns = np.diff(closes) / np.maximum(closes[:-1], 1e-12) * 10_000.0
    return float(np.std(returns)) if len(returns) else 0.0


def _max_drawdown_bps(closes: np.ndarray) -> float:
    if len(closes) < 2:
        return 0.0
    running_high = np.maximum.accumulate(closes)
    drawdowns = closes / np.maximum(running_high, 1e-12) - 1.0
    return float(np.min(drawdowns) * 10_000.0)


def _trend_slope_bps(closes: np.ndarray) -> float:
    if len(closes) < 2:
        return 0.0
    x = np.arange(len(closes), dtype=np.float64)
    y = np.log(np.maximum(closes, 1e-12))
    slope = np.polyfit(x, y, deg=1)[0]
    return float(slope * 10_000.0)


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2.0 / (span + 1.0)
    output = np.empty_like(values, dtype=np.float64)
    output[0] = values[0]
    for index in range(1, len(values)):
        output[index] = alpha * values[index] + (1.0 - alpha) * output[index - 1]
    return output


def _macd_bps(closes: np.ndarray) -> float:
    if len(closes) < 2:
        return 0.0
    fast = _ema(closes, span=min(12, max(2, len(closes) // 3)))
    slow = _ema(closes, span=min(26, max(3, len(closes) // 2)))
    return _return_bps(float(slow[-1]), float(fast[-1]))


def _bollinger_position(closes: np.ndarray) -> float:
    lookback = closes[-min(20, len(closes)) :]
    mean = float(np.mean(lookback))
    std = float(np.std(lookback))
    if std <= 1e-12:
        return 0.0
    return float((closes[-1] - mean) / (2.0 * std))


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < 2:
        return 50.0
    deltas = np.diff(closes)
    recent = deltas[-period:]
    gains = np.maximum(recent, 0.0)
    losses = np.maximum(-recent, 0.0)
    avg_gain = float(np.mean(gains)) if len(gains) else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) else 0.0
    if avg_loss <= 1e-12 and avg_gain <= 1e-12:
        return 50.0
    if avg_loss <= 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _direction_bucket(value: float, *, threshold: float) -> str:
    if value > threshold:
        return "up"
    if value < -threshold:
        return "down"
    return "flat"


def _rsi_bucket(value: float) -> str:
    if value < 35.0:
        return "oversold"
    if value > 65.0:
        return "overbought"
    return "neutral"


def _three_bucket(value: float, *, low: float, high: float, labels: tuple[str, str, str]) -> str:
    if value < low:
        return labels[0]
    if value > high:
        return labels[2]
    return labels[1]
