from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_capitulation_asset_transfer_benchmark import (  # noqa: E402
    FROZEN_TRANSFER_CONFIG,
    _aggregate_evidence_70,
)
from benchmarks.crypto_capitulation_confirmation_benchmark import (  # noqa: E402
    FOLD_BOUNDARIES,
    _percent,
    evaluate_config,
)
from benchmarks.crypto_capitulation_coverage_benchmark import (  # noqa: E402
    _admitted_70,
)
from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402
from benchmarks.crypto_multiyear_event_benchmark import (  # noqa: E402
    assign_calendar_folds,
)


API_BASE_URL = "https://api.bybit.com/v5/market"
CACHE_SCHEMA = "wavemind.crypto.bybit-public-v1"
BAR_SECONDS = 4 * 60 * 60
DEFAULT_START = "2023-01-01"
DEFAULT_END = "2026-07-27"
DEFAULT_SYMBOLS = (
    "NEARUSDT",
    "SNXUSDT",
    "CRVUSDT",
    "KAVAUSDT",
    "IOTAUSDT",
    "ENJUSDT",
    "OPUSDT",
    "APTUSDT",
)
HORIZONS = {
    "12h": 3,
    "24h": 6,
    "48h": 12,
    "7d": 42,
}
ANALOGUE_FEATURES = (
    "return_1",
    "return_2",
    "return_3",
    "return_6",
    "return_12",
    "return_18",
    "return_36",
    "return_72",
    "return_126",
    "oi_change_1",
    "oi_change_3",
    "oi_change_6",
    "oi_change_12",
    "oi_change_18",
    "oi_change_36",
    "oi_change_72",
    "volatility_6",
    "volatility_12",
    "volatility_36",
    "volatility_72",
    "turnover_z_6",
    "turnover_z_12",
    "turnover_z_36",
    "turnover_z_72",
    "position_6",
    "position_12",
    "position_36",
    "position_72",
    "drawdown_6",
    "drawdown_12",
    "drawdown_36",
    "drawdown_72",
    "candle_range",
    "candle_body",
    "deceleration",
)
BYBIT_FOLD_BOUNDARIES = FOLD_BOUNDARIES + (("2026-07-01", DEFAULT_END),)
ALL_BYBIT_FOLDS = tuple(range(len(BYBIT_FOLD_BOUNDARIES)))


@dataclass(frozen=True)
class BybitKline:
    start_timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


@dataclass(frozen=True)
class BybitOpenInterest:
    timestamp: int
    open_interest: float


@dataclass(frozen=True)
class BybitInstrument:
    symbol: str
    klines: tuple[BybitKline, ...]
    open_interest: tuple[BybitOpenInterest, ...]


RequestJson = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class BybitPublicClient:
    def __init__(
        self,
        *,
        request_json: RequestJson | None = None,
        retries: int = 5,
        request_pause: float = 0.03,
    ) -> None:
        self.request_json = request_json or self._request_json
        self.retries = retries
        self.request_pause = request_pause

    def fetch_instrument(
        self,
        symbol: str,
        *,
        start_timestamp: int,
        end_timestamp: int,
    ) -> BybitInstrument:
        return BybitInstrument(
            symbol=symbol,
            klines=tuple(
                self.fetch_klines(
                    symbol,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                )
            ),
            open_interest=tuple(
                self.fetch_open_interest(
                    symbol,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                )
            ),
        )

    def fetch_klines(
        self,
        symbol: str,
        *,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[BybitKline]:
        rows: dict[int, BybitKline] = {}
        page_end = end_timestamp * 1000
        start_ms = start_timestamp * 1000
        while page_end >= start_ms:
            payload = self._get(
                "kline",
                {
                    "category": "linear",
                    "symbol": symbol,
                    "interval": "240",
                    "start": start_ms,
                    "end": page_end,
                    "limit": 1000,
                },
            )
            raw_rows = payload["result"].get("list", [])
            if not raw_rows:
                break
            oldest_ms = page_end
            for raw in raw_rows:
                timestamp_ms = int(raw[0])
                oldest_ms = min(oldest_ms, timestamp_ms)
                if start_ms <= timestamp_ms <= end_timestamp * 1000:
                    timestamp = timestamp_ms // 1000
                    rows[timestamp] = BybitKline(
                        start_timestamp=timestamp,
                        open=float(raw[1]),
                        high=float(raw[2]),
                        low=float(raw[3]),
                        close=float(raw[4]),
                        volume=float(raw[5]),
                        turnover=float(raw[6]),
                    )
            if oldest_ms <= start_ms:
                break
            next_end = oldest_ms - 1
            if next_end >= page_end:
                raise RuntimeError(f"{symbol}: kline pagination made no progress")
            page_end = next_end
            self._pause()
        return [rows[timestamp] for timestamp in sorted(rows)]

    def fetch_open_interest(
        self,
        symbol: str,
        *,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[BybitOpenInterest]:
        rows: dict[int, BybitOpenInterest] = {}
        cursor = ""
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": "4h",
                "startTime": start_timestamp * 1000,
                "endTime": end_timestamp * 1000,
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            payload = self._get("open-interest", params)
            result = payload["result"]
            for raw in result.get("list", []):
                timestamp_ms = int(raw["timestamp"])
                if start_timestamp * 1000 <= timestamp_ms <= end_timestamp * 1000:
                    timestamp = timestamp_ms // 1000
                    rows[timestamp] = BybitOpenInterest(
                        timestamp=timestamp,
                        open_interest=float(raw["openInterest"]),
                    )
            next_cursor = str(result.get("nextPageCursor") or "")
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(
                    f"{symbol}: open-interest pagination repeated a cursor"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            self._pause()
        return [rows[timestamp] for timestamp in sorted(rows)]

    def _get(self, endpoint: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                payload = self.request_json(endpoint, params)
                if int(payload.get("retCode", -1)) != 0:
                    raise RuntimeError(
                        f"Bybit error {payload.get('retCode')}: "
                        f"{payload.get('retMsg')}"
                    )
                if not isinstance(payload.get("result"), Mapping):
                    raise RuntimeError("Bybit response has no result object")
                return payload
            except (
                OSError,
                TimeoutError,
                urllib.error.URLError,
                RuntimeError,
            ) as exc:
                last_error = exc
                if attempt + 1 == self.retries:
                    break
                time.sleep(min(0.5 * (2**attempt), 8.0))
        raise RuntimeError(
            f"Bybit request failed after {self.retries} attempts"
        ) from last_error

    def _request_json(
        self,
        endpoint: str,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        url = (
            f"{API_BASE_URL}/{endpoint}?"
            + urllib.parse.urlencode(params)
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "WaveMind-research/1.0"},
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)

    def _pause(self) -> None:
        if self.request_pause > 0.0:
            time.sleep(self.request_pause)


def load_or_download_dataset(
    symbols: Sequence[str],
    *,
    cache_path: str | Path,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    client: BybitPublicClient | None = None,
    refresh: bool = False,
) -> tuple[list[BybitInstrument], dict[str, Any]]:
    normalized = sorted({symbol.upper() for symbol in symbols})
    if not normalized:
        raise ValueError("symbols must not be empty")
    path = Path(cache_path)
    instruments: list[BybitInstrument] = []
    if path.exists() and not refresh:
        payload = _read_gzip_json(path)
        if (
            payload.get("schema") == CACHE_SCHEMA
            and payload.get("start") == start
            and payload.get("end") == end
        ):
            cached = [_instrument(row) for row in payload["instruments"]]
            cached_symbols = {instrument.symbol for instrument in cached}
            if cached_symbols <= set(normalized):
                instruments = cached
            cached_symbols = {instrument.symbol for instrument in instruments}
            if cached_symbols == set(normalized):
                return instruments, _provenance(payload, path)

    start_timestamp = _timestamp(start)
    end_timestamp = _timestamp(end)
    if end_timestamp <= start_timestamp:
        raise ValueError("end must be after start")
    public_client = client or BybitPublicClient()
    completed = {instrument.symbol for instrument in instruments}
    for symbol in normalized:
        if symbol in completed:
            continue
        instrument = public_client.fetch_instrument(
            symbol,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        _validate_instrument(instrument)
        instruments.append(instrument)
        instruments.sort(key=lambda item: item.symbol)
        completed.add(symbol)
        payload = _dataset_payload(
            instruments,
            symbols=normalized,
            start=start,
            end=end,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_gzip_json(path, payload)
        print(
            f"{symbol}: {len(instrument.klines)} klines, "
            f"{len(instrument.open_interest)} OI points",
            flush=True,
        )
    payload = _dataset_payload(
        instruments,
        symbols=normalized,
        start=start,
        end=end,
    )
    _write_gzip_json(path, payload)
    return instruments, _provenance(payload, path)


def build_feature_rows(
    instruments: Sequence[BybitInstrument],
    *,
    horizon: int,
) -> list[FeatureRow]:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    output: list[FeatureRow] = []
    for instrument in instruments:
        bars = list(instrument.klines)
        aligned_oi = _align_open_interest(instrument)

        for index in range(12, len(bars) - horizon):
            target_index = index + horizon
            required = (index - 12, index - 3, index - 1, index, target_index)
            if not _contiguous(bars, required):
                continue
            current_oi = aligned_oi[index]
            previous_oi = aligned_oi[index - 1]
            if (
                current_oi is None
                or previous_oi is None
                or previous_oi <= 0.0
            ):
                continue
            current = bars[index]
            current_close = current.close
            if current_close <= 0.0:
                continue
            observed_at = current.start_timestamp + BAR_SECONDS
            target_at = bars[target_index].start_timestamp + BAR_SECONDS
            output.append(
                FeatureRow(
                    symbol=instrument.symbol,
                    timestamp=observed_at,
                    target_timestamp=target_at,
                    fold_index=-1,
                    features={
                        "return_1": _return_bps(
                            current_close,
                            bars[index - 1].close,
                        ),
                        "return_3": _return_bps(
                            current_close,
                            bars[index - 3].close,
                        ),
                        "return_12": _return_bps(
                            current_close,
                            bars[index - 12].close,
                        ),
                        "oi_change_1": _return_bps(
                            current_oi,
                            previous_oi,
                        ),
                        "taker_imbalance": 0.0,
                    },
                    future_return_bps=_return_bps(
                        bars[target_index].close,
                        current_close,
                    ),
                )
            )
    return sorted(output, key=lambda row: (row.timestamp, row.symbol))


def build_analogue_feature_rows(
    instruments: Sequence[BybitInstrument],
    *,
    horizon: int = 6,
) -> list[FeatureRow]:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    output: list[FeatureRow] = []
    for instrument in instruments:
        bars = list(instrument.klines)
        aligned_oi = _align_open_interest(
            instrument,
            include_close_boundary=False,
        )
        closes = np.asarray([bar.close for bar in bars], dtype=float)
        highs = np.asarray([bar.high for bar in bars], dtype=float)
        lows = np.asarray([bar.low for bar in bars], dtype=float)
        turnovers = np.log1p(
            np.asarray([bar.turnover for bar in bars], dtype=float)
        )
        one_bar_returns = np.full(len(bars), np.nan, dtype=float)
        one_bar_returns[1:] = (
            closes[1:] / closes[:-1] - 1.0
        ) * 10_000.0
        for index in range(126, len(bars) - horizon):
            target_index = index + horizon
            required = (
                index - 126,
                index - 72,
                index - 36,
                index - 18,
                index - 12,
                index - 6,
                index - 3,
                index - 2,
                index - 1,
                index,
                target_index,
            )
            if not _contiguous(bars, required):
                continue
            current_oi = aligned_oi[index]
            if current_oi is None or current_oi <= 0.0:
                continue
            oi_changes: dict[int, float] = {}
            missing_oi = False
            for lag in (1, 3, 6, 12, 18, 36, 72):
                previous = aligned_oi[index - lag]
                if previous is None or previous <= 0.0:
                    missing_oi = True
                    break
                oi_changes[lag] = _return_bps(current_oi, previous)
            if missing_oi:
                continue
            current = bars[index]
            features: dict[str, float] = {}
            for lag in (1, 2, 3, 6, 12, 18, 36, 72, 126):
                features[f"return_{lag}"] = _return_bps(
                    current.close,
                    bars[index - lag].close,
                )
            for lag, value in oi_changes.items():
                features[f"oi_change_{lag}"] = value
            for window in (6, 12, 36, 72):
                start = index - window + 1
                returns = one_bar_returns[start : index + 1]
                volume = turnovers[start : index + 1]
                window_high = float(np.max(highs[start : index + 1]))
                window_low = float(np.min(lows[start : index + 1]))
                volume_scale = float(np.std(volume))
                features[f"volatility_{window}"] = float(np.std(returns))
                features[f"turnover_z_{window}"] = (
                    float((turnovers[index] - np.mean(volume)) / volume_scale)
                    if volume_scale > 1e-12
                    else 0.0
                )
                price_range = window_high - window_low
                features[f"position_{window}"] = (
                    float((current.close - window_low) / price_range)
                    if price_range > 1e-12
                    else 0.5
                )
                features[f"drawdown_{window}"] = _return_bps(
                    current.close,
                    window_high,
                )
            features["candle_range"] = _return_bps(
                current.high,
                current.low,
            )
            features["candle_body"] = _return_bps(
                current.close,
                current.open,
            )
            features["deceleration"] = (
                features["return_1"] - features["return_3"] / 3.0
            )
            if not all(
                np.isfinite(features[name]) for name in ANALOGUE_FEATURES
            ):
                continue
            output.append(
                FeatureRow(
                    symbol=instrument.symbol,
                    timestamp=current.start_timestamp + BAR_SECONDS,
                    target_timestamp=(
                        bars[target_index].start_timestamp + BAR_SECONDS
                    ),
                    fold_index=-1,
                    features=features,
                    future_return_bps=_return_bps(
                        bars[target_index].close,
                        current.close,
                    ),
                )
            )
    return sorted(output, key=lambda row: (row.timestamp, row.symbol))


def run_cross_exchange_benchmark(
    rows_by_horizon: Mapping[str, Sequence[FeatureRow]],
    *,
    symbols: Sequence[str],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    expected = set(HORIZONS)
    if set(rows_by_horizon) != expected:
        raise ValueError(
            "rows_by_horizon must contain " + ", ".join(sorted(expected))
        )
    results: dict[str, Any] = {}
    for label in HORIZONS:
        folded = assign_calendar_folds(
            rows_by_horizon[label],
            boundaries=BYBIT_FOLD_BOUNDARIES,
        )
        results[label] = evaluate_config(
            folded,
            config=FROZEN_TRANSFER_CONFIG,
            folds=ALL_BYBIT_FOLDS,
        )
    primary = results["24h"]["summary"]
    return {
        "benchmark": "frozen cross-exchange post-capitulation transfer",
        "methodology": {
            "source": "official Bybit V5 public market API",
            "source_urls": {
                "kline": (
                    "https://bybit-exchange.github.io/docs/v5/market/kline"
                ),
                "open_interest": (
                    "https://bybit-exchange.github.io/docs/v5/market/"
                    "open-interest"
                ),
            },
            "selection": (
                "The return threshold, open-interest threshold, confirmation "
                "rule, symbols, horizons, and fold boundaries were declared "
                "before this Bybit dataset was evaluated."
            ),
            "exchange_transfer": (
                "No Bybit observation was used to choose or tune the frozen "
                "Binance-derived rule."
            ),
            "overlap_control": (
                "Signals are evaluated on completed 4h bars and collapsed per "
                "asset until the forecast horizon matures."
            ),
            "fold_boundaries": [
                list(boundary) for boundary in BYBIT_FOLD_BOUNDARIES
            ],
        },
        "frozen_config": asdict(FROZEN_TRANSFER_CONFIG),
        "symbols": sorted(symbols),
        "provenance": dict(provenance),
        "horizons": results,
        "primary_24h_aggregate_evidence_70": _aggregate_evidence_70(primary),
        "primary_24h_admitted_70": _admitted_70(primary),
        "all_horizons_aggregate_70": all(
            _aggregate_evidence_70(result["summary"])
            for result in results.values()
        ),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    config = payload["frozen_config"]
    lines = [
        "# Frozen Cross-Exchange Post-Capitulation Transfer",
        "",
        (
            "The Binance-derived rule is evaluated unchanged on official "
            "Bybit data, new assets, four forecast horizons, and a new July "
            "2026 fold."
        ),
        "",
        f"- assets: {', '.join(payload['symbols'])};",
        (
            "- frozen rule: return q"
            f"{config['return_quantile']:.2f}, OI q"
            f"{config['oi_quantile']:.2f}, {config['confirmation']};"
        ),
        "- source interval: 4h completed candles and 4h open interest;",
        (
            f"- dataset SHA-256: `{payload['provenance']['dataset_sha256']}`."
        ),
        "",
        "| horizon | signals | coverage | accuracy | Wilson low 95% | worst fold | worst asset |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, result in payload["horizons"].items():
        summary = result["summary"]
        lines.append(
            f"| {label} | {summary['signals']} | "
            f"{_percent(summary['coverage'])} | "
            f"{_percent(summary['accuracy'])} | "
            f"{_percent(summary['wilson_low_95'])} | "
            f"{_percent(summary['worst_supported_fold_accuracy'])} | "
            f"{_percent(summary['worst_supported_symbol_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            (
                "24h aggregate 70% evidence: "
                + (
                    "**passed**"
                    if payload["primary_24h_aggregate_evidence_70"]
                    else "**rejected**"
                )
            ),
            "",
            (
                "24h stable admission: "
                + (
                    "**passed**"
                    if payload["primary_24h_admitted_70"]
                    else "**rejected**"
                )
            ),
            "",
            (
                "All-horizon aggregate 70% evidence: "
                + (
                    "**passed**"
                    if payload["all_horizons_aggregate_70"]
                    else "**rejected**"
                )
            ),
            "",
            "## 24h Time Folds",
            "",
            "| fold | signals | accuracy | Wilson low 95% |",
            "|---:|---:|---:|---:|",
        ]
    )
    for row in payload["horizons"]["24h"]["summary"]["by_fold"]:
        lines.append(
            f"| {row['fold_index']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            "## 24h Assets",
            "",
            "| asset | signals | accuracy | Wilson low 95% |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload["horizons"]["24h"]["summary"]["by_symbol"]:
        lines.append(
            f"| {row['symbol']} | {row['signals']} | "
            f"{_percent(row['accuracy'])} | "
            f"{_percent(row['wilson_low_95'])} |"
        )
    lines.extend(
        [
            "",
            (
                "This is a transfer test, not a threshold search. A result is "
                "not admitted merely because its average exceeds 70%; the "
                "Wilson, fold, asset, and support gates remain binding."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _dataset_payload(
    instruments: Sequence[BybitInstrument],
    *,
    symbols: Sequence[str],
    start: str,
    end: str,
) -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA,
        "source": API_BASE_URL,
        "symbols": list(symbols),
        "start": start,
        "end": end,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "instruments": [asdict(instrument) for instrument in instruments],
    }


def _provenance(payload: Mapping[str, Any], path: Path) -> dict[str, Any]:
    canonical = json.dumps(
        {
            key: payload[key]
            for key in (
                "schema",
                "source",
                "symbols",
                "start",
                "end",
                "instruments",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "cache_path": str(path.as_posix()),
        "source": payload["source"],
        "start": payload["start"],
        "end": payload["end"],
        "downloaded_at": payload["downloaded_at"],
        "dataset_sha256": hashlib.sha256(canonical).hexdigest(),
        "instrument_counts": {
            row["symbol"]: {
                "klines": len(row["klines"]),
                "open_interest": len(row["open_interest"]),
            }
            for row in payload["instruments"]
        },
    }


def _instrument(payload: Mapping[str, Any]) -> BybitInstrument:
    return BybitInstrument(
        symbol=str(payload["symbol"]),
        klines=tuple(BybitKline(**row) for row in payload["klines"]),
        open_interest=tuple(
            BybitOpenInterest(**row) for row in payload["open_interest"]
        ),
    )


def _validate_instrument(instrument: BybitInstrument) -> None:
    if len(instrument.klines) < 100:
        raise ValueError(f"{instrument.symbol}: too few klines")
    if len(instrument.open_interest) < 100:
        raise ValueError(f"{instrument.symbol}: too few open-interest points")
    if any(row.close <= 0.0 for row in instrument.klines):
        raise ValueError(f"{instrument.symbol}: non-positive close")
    if any(row.open_interest < 0.0 for row in instrument.open_interest):
        raise ValueError(f"{instrument.symbol}: negative open interest")


def _align_open_interest(
    instrument: BybitInstrument,
    *,
    include_close_boundary: bool = True,
) -> list[float | None]:
    open_interest = list(instrument.open_interest)
    oi_cursor = 0
    latest_oi: BybitOpenInterest | None = None
    aligned: list[float | None] = []
    for bar in instrument.klines:
        observed_at = bar.start_timestamp + BAR_SECONDS
        while (
            oi_cursor < len(open_interest)
            and (
                open_interest[oi_cursor].timestamp <= observed_at
                if include_close_boundary
                else open_interest[oi_cursor].timestamp < observed_at
            )
        ):
            latest_oi = open_interest[oi_cursor]
            oi_cursor += 1
        if latest_oi is None or observed_at - latest_oi.timestamp > BAR_SECONDS:
            aligned.append(None)
        else:
            aligned.append(latest_oi.open_interest)
    return aligned


def _contiguous(
    bars: Sequence[BybitKline],
    indices: Sequence[int],
) -> bool:
    current = bars[indices[-2]].start_timestamp
    for index in indices:
        expected = current + (index - indices[-2]) * BAR_SECONDS
        if bars[index].start_timestamp != expected:
            return False
    return True


def _return_bps(current: float, previous: float) -> float:
    if previous <= 0.0:
        raise ValueError("previous value must be positive")
    return (current / previous - 1.0) * 10_000.0


def _timestamp(value: str) -> int:
    return int(
        datetime.fromisoformat(value)
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def _write_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as sink:
        json.dump(payload, sink, separators=(",", ":"))
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a frozen Binance-derived capitulation rule on Bybit."
        )
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="Bybit linear perpetual symbol; repeat for multiple assets.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("data/bybit-capitulation-transfer-v1.json.gz"),
    )
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    symbols = tuple(args.symbols or DEFAULT_SYMBOLS)
    instruments, provenance = load_or_download_dataset(
        symbols,
        cache_path=args.cache,
        start=args.start,
        end=args.end,
        refresh=args.refresh,
    )
    rows_by_horizon = {
        label: build_feature_rows(instruments, horizon=bars)
        for label, bars in HORIZONS.items()
    }
    payload = run_cross_exchange_benchmark(
        rows_by_horizon,
        symbols=symbols,
        provenance=provenance,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    summary = payload["horizons"]["24h"]["summary"]
    print(
        f"24h accuracy={_percent(summary['accuracy'])} "
        f"signals={summary['signals']} "
        f"aggregate_70={payload['primary_24h_aggregate_evidence_70']} "
        f"admitted_70={payload['primary_24h_admitted_70']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
