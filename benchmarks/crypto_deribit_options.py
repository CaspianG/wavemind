from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_derivatives_field_benchmark import FeatureRow  # noqa: E402


DERIBIT_HISTORY_API = (
    "https://history.deribit.com/api/v2/public/"
    "get_last_trades_by_currency_and_time"
)
CURRENCY_BY_SYMBOL = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
INSTRUMENT_RE = re.compile(
    r"^(?P<currency>[A-Z]+)-(?P<expiry>\d{1,2}[A-Z]{3}\d{2})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<kind>[CP])$"
)
OPTIONS_FEATURES = (
    "options_atm_iv",
    "options_skew_iv",
    "options_term_spread_iv",
    "options_put_call_log_ratio",
    "options_directional_flow",
    "options_skew_change_1d",
    "options_skew_change_7d",
    "options_flow_mean_7d",
    "options_atm_iv_z30",
    "options_skew_z30",
    "options_volume_log",
    "btc_options_skew_iv",
    "btc_options_directional_flow",
    "options_age_days",
)


@dataclass(frozen=True)
class OptionsDailySummary:
    symbol: str
    currency: str
    trading_date: str
    available_timestamp: int
    sampled_trades: int
    sample_truncated: bool
    total_contracts: float
    atm_iv: float
    otm_put_iv: float
    otm_call_iv: float
    skew_iv: float
    term_spread_iv: float
    put_call_log_ratio: float
    directional_flow: float
    source_sha256: str


@dataclass(frozen=True)
class OptionsDataset:
    start_date: str
    end_date: str
    sample_count: int
    sample_windows: tuple[str, ...]
    summaries: tuple[OptionsDailySummary, ...]
    source_endpoint: str
    missing_days: tuple[str, ...]


def download_options_dataset(
    *,
    symbols: Sequence[str],
    start: date,
    end: date,
    sample_count: int = 250,
    workers: int = 6,
    endpoint: str = DERIBIT_HISTORY_API,
    fetcher: Callable[[str], bytes] | None = None,
    cache_dir: str | Path | None = None,
) -> OptionsDataset:
    if start > end:
        raise ValueError("start must be on or before end")
    if sample_count <= 0 or sample_count > 1000:
        raise ValueError("sample_count must be between 1 and 1000")
    if workers <= 0:
        raise ValueError("workers must be positive")
    normalized = tuple(dict.fromkeys(symbol.upper() for symbol in symbols))
    unknown = sorted(set(normalized) - set(CURRENCY_BY_SYMBOL))
    if unknown:
        raise ValueError("Unsupported option underlyings: " + ", ".join(unknown))
    read = fetcher or _read_url
    jobs = [
        (symbol, CURRENCY_BY_SYMBOL[symbol], day)
        for symbol in normalized
        for day in _days(start, end)
    ]
    summaries: list[OptionsDailySummary] = []
    missing: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download_day,
                symbol=symbol,
                currency=currency,
                day=day,
                sample_count=sample_count,
                endpoint=endpoint,
                fetcher=read,
                cache_dir=Path(cache_dir) if cache_dir is not None else None,
            ): (symbol, day)
            for symbol, currency, day in jobs
        }
        for future in as_completed(futures):
            symbol, day = futures[future]
            summary = future.result()
            if summary is None:
                missing.append(f"{symbol}:{day.isoformat()}")
            else:
                summaries.append(summary)
    return OptionsDataset(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        sample_count=sample_count,
        sample_windows=("open", "midday", "close"),
        summaries=tuple(
            sorted(summaries, key=lambda row: (row.symbol, row.available_timestamp))
        ),
        source_endpoint=endpoint,
        missing_days=tuple(sorted(missing)),
    )


def summarize_option_trades(
    trades: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    currency: str,
    trading_date: date,
    source_sha256: str,
    sample_truncated: bool,
) -> OptionsDailySummary | None:
    parsed = []
    seen: set[str] = set()
    for trade in trades:
        trade_id = str(trade.get("trade_id", ""))
        if not trade_id or trade_id in seen:
            continue
        seen.add(trade_id)
        match = INSTRUMENT_RE.match(str(trade.get("instrument_name", "")))
        if match is None or match.group("currency") != currency:
            continue
        try:
            timestamp = int(trade["timestamp"])
            index_price = float(trade["index_price"])
            strike = float(match.group("strike"))
            iv = float(trade["iv"])
            amount = float(trade.get("amount", trade.get("contracts", 0.0)))
            expiry = datetime.strptime(
                match.group("expiry"), "%d%b%y"
            ).replace(hour=8, tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        observed = datetime.fromtimestamp(timestamp / 1000.0, tz=timezone.utc)
        dte = (expiry - observed).total_seconds() / 86_400.0
        if not (
            index_price > 0.0
            and amount > 0.0
            and 0.0 < iv < 500.0
            and 2.0 <= dte <= 120.0
        ):
            continue
        moneyness = strike / index_price
        kind = match.group("kind")
        direction = str(trade.get("direction", "")).lower()
        signed = 1.0 if direction == "buy" else -1.0
        parsed.append((kind, moneyness, dte, iv, amount, signed))
    if not parsed:
        return None

    total = sum(row[4] for row in parsed)
    calls = sum(row[4] for row in parsed if row[0] == "C")
    puts = sum(row[4] for row in parsed if row[0] == "P")
    atm_iv = _weighted_mean(
        [(row[3], row[4]) for row in parsed if abs(math.log(row[1])) <= 0.05]
    )
    put_iv = _weighted_mean(
        [(row[3], row[4]) for row in parsed if row[0] == "P" and 0.75 <= row[1] <= 1.0]
    )
    call_iv = _weighted_mean(
        [(row[3], row[4]) for row in parsed if row[0] == "C" and 1.0 <= row[1] <= 1.25]
    )
    front_iv = _weighted_mean(
        [(row[3], row[4]) for row in parsed if row[2] <= 14.0]
    )
    back_iv = _weighted_mean(
        [(row[3], row[4]) for row in parsed if 30.0 <= row[2] <= 90.0]
    )
    values = (atm_iv, put_iv, call_iv, front_iv, back_iv)
    if not all(math.isfinite(value) for value in values):
        return None
    directional = sum(
        amount * signed * (1.0 if kind == "C" else -1.0)
        for kind, _, _, _, amount, signed in parsed
    ) / max(total, 1e-12)
    return OptionsDailySummary(
        symbol=symbol,
        currency=currency,
        trading_date=trading_date.isoformat(),
        available_timestamp=_midnight(trading_date + timedelta(days=1)),
        sampled_trades=len(parsed),
        sample_truncated=sample_truncated,
        total_contracts=float(total),
        atm_iv=float(atm_iv),
        otm_put_iv=float(put_iv),
        otm_call_iv=float(call_iv),
        skew_iv=float(put_iv - call_iv),
        term_spread_iv=float(front_iv - back_iv),
        put_call_log_ratio=float(math.log((puts + 1e-9) / (calls + 1e-9))),
        directional_flow=float(directional),
        source_sha256=source_sha256,
    )


def add_options_features(
    rows: Sequence[FeatureRow],
    dataset: OptionsDataset,
    *,
    min_history: int = 30,
    max_age_days: float = 3.0,
) -> list[FeatureRow]:
    if min_history < 7:
        raise ValueError("min_history must be at least 7 days")
    if max_age_days <= 0.0:
        raise ValueError("max_age_days must be positive")
    series = _feature_series(dataset)
    output = []
    for row in rows:
        own = series.get(row.symbol)
        btc = series.get("BTCUSDT")
        if own is None or btc is None:
            continue
        own_point = _asof(own, row.timestamp)
        btc_point = _asof(btc, row.timestamp)
        if (
            own_point is None
            or btc_point is None
            or int(own_point["history"]) < min_history
            or int(btc_point["history"]) < min_history
        ):
            continue
        age = (row.timestamp - int(own_point["available_timestamp"])) / 86_400.0
        btc_age = (row.timestamp - int(btc_point["available_timestamp"])) / 86_400.0
        if min(age, btc_age) < 0.0 or max(age, btc_age) > max_age_days:
            continue
        additions = {
            name: float(own_point[name])
            for name in OPTIONS_FEATURES
            if name not in {"btc_options_skew_iv", "btc_options_directional_flow", "options_age_days"}
        }
        additions.update(
            {
                "btc_options_skew_iv": float(btc_point["options_skew_iv"]),
                "btc_options_directional_flow": float(
                    btc_point["options_directional_flow"]
                ),
                "options_age_days": float(max(age, btc_age)),
            }
        )
        output.append(
            FeatureRow(
                symbol=row.symbol,
                timestamp=row.timestamp,
                target_timestamp=row.target_timestamp,
                fold_index=row.fold_index,
                features=dict(row.features) | additions,
                future_return_bps=row.future_return_bps,
            )
        )
    return output


def save_options_dataset(path: str | Path, dataset: OptionsDataset) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": dataset.start_date,
        "end_date": dataset.end_date,
        "sample_count": dataset.sample_count,
        "sample_windows": list(dataset.sample_windows),
        "summaries": [asdict(row) for row in dataset.summaries],
        "source_endpoint": dataset.source_endpoint,
        "missing_days": list(dataset.missing_days),
    }
    content = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    if output.suffix == ".gz":
        with gzip.open(output, "wb", compresslevel=6) as handle:
            handle.write(content)
    else:
        output.write_bytes(content)


def load_options_dataset(path: str | Path) -> OptionsDataset:
    source = Path(path)
    if source.suffix == ".gz":
        with gzip.open(source, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return OptionsDataset(
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        sample_count=int(payload["sample_count"]),
        sample_windows=tuple(str(item) for item in payload["sample_windows"]),
        summaries=tuple(OptionsDailySummary(**row) for row in payload["summaries"]),
        source_endpoint=str(payload["source_endpoint"]),
        missing_days=tuple(str(item) for item in payload.get("missing_days", [])),
    )


def merge_options_datasets(*datasets: OptionsDataset) -> OptionsDataset:
    if not datasets:
        raise ValueError("At least one options dataset is required")
    first = datasets[0]
    for dataset in datasets[1:]:
        if (
            dataset.sample_count != first.sample_count
            or dataset.sample_windows != first.sample_windows
            or dataset.source_endpoint != first.source_endpoint
        ):
            raise ValueError("Options datasets use incompatible sampling configurations")
    summaries = {
        (row.symbol, row.trading_date): row
        for dataset in datasets
        for row in dataset.summaries
    }
    return OptionsDataset(
        start_date=min(dataset.start_date for dataset in datasets),
        end_date=max(dataset.end_date for dataset in datasets),
        sample_count=first.sample_count,
        sample_windows=first.sample_windows,
        summaries=tuple(
            sorted(
                summaries.values(),
                key=lambda row: (row.symbol, row.available_timestamp),
            )
        ),
        source_endpoint=first.source_endpoint,
        missing_days=tuple(
            sorted({item for dataset in datasets for item in dataset.missing_days})
        ),
    )


def _download_day(
    *,
    symbol: str,
    currency: str,
    day: date,
    sample_count: int,
    endpoint: str,
    fetcher: Callable[[str], bytes],
    cache_dir: Path | None,
) -> OptionsDailySummary | None:
    start = _midnight(day) * 1000
    end = _midnight(day + timedelta(days=1)) * 1000 - 1
    requests = (
        ("open", start, end, "asc"),
        ("midday", start + 12 * 3_600_000, end, "asc"),
        ("close", start, end, "desc"),
    )
    raw_responses = []
    trades = []
    truncated = False
    for window, request_start, request_end, sorting in requests:
        query = urllib.parse.urlencode(
            {
                "currency": currency,
                "kind": "option",
                "start_timestamp": request_start,
                "end_timestamp": request_end,
                "count": sample_count,
                "sorting": sorting,
            }
        )
        url = f"{endpoint}?{query}"
        cache_path = (
            cache_dir / currency / f"{day.isoformat()}-{window}.json.gz"
            if cache_dir is not None
            else None
        )
        raw = _cached_response(cache_path, url=url, fetcher=fetcher)
        payload = json.loads(raw)
        if "error" in payload:
            raise RuntimeError(f"Deribit API error: {payload['error']}")
        result = payload.get("result", {})
        raw_responses.append(raw)
        trades.extend(result.get("trades", []))
        truncated = truncated or bool(result.get("has_more"))
    digest = hashlib.sha256()
    for raw in raw_responses:
        digest.update(hashlib.sha256(raw).digest())
    return summarize_option_trades(
        trades,
        symbol=symbol,
        currency=currency,
        trading_date=day,
        source_sha256=digest.hexdigest(),
        sample_truncated=truncated,
    )


def _cached_response(
    path: Path | None,
    *,
    url: str,
    fetcher: Callable[[str], bytes],
) -> bytes:
    if path is None:
        return fetcher(url)
    if path.exists():
        with gzip.open(path, "rb") as handle:
            return handle.read()
    raw = fetcher(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with gzip.open(temporary, "wb", compresslevel=6) as handle:
        handle.write(raw)
    temporary.replace(path)
    return raw


def _feature_series(
    dataset: OptionsDataset,
) -> dict[str, tuple[tuple[int, Mapping[str, float]], ...]]:
    grouped: dict[str, list[OptionsDailySummary]] = {}
    for summary in dataset.summaries:
        grouped.setdefault(summary.symbol, []).append(summary)
    output = {}
    for symbol, summaries in grouped.items():
        ordered = sorted(summaries, key=lambda row: row.available_timestamp)
        skew_history: list[float] = []
        iv_history: list[float] = []
        flow_history: list[float] = []
        points = []
        for summary in ordered:
            skew_history.append(summary.skew_iv)
            iv_history.append(summary.atm_iv)
            flow_history.append(summary.directional_flow)
            skew_window = np.asarray(skew_history[-30:], dtype=float)
            iv_window = np.asarray(iv_history[-30:], dtype=float)
            points.append(
                (
                    summary.available_timestamp,
                    {
                        "history": float(len(points) + 1),
                        "available_timestamp": float(summary.available_timestamp),
                        "options_atm_iv": summary.atm_iv,
                        "options_skew_iv": summary.skew_iv,
                        "options_term_spread_iv": summary.term_spread_iv,
                        "options_put_call_log_ratio": summary.put_call_log_ratio,
                        "options_directional_flow": summary.directional_flow,
                        "options_skew_change_1d": summary.skew_iv
                        - (skew_history[-2] if len(skew_history) >= 2 else summary.skew_iv),
                        "options_skew_change_7d": summary.skew_iv
                        - (skew_history[-8] if len(skew_history) >= 8 else skew_history[0]),
                        "options_flow_mean_7d": float(np.mean(flow_history[-7:])),
                        "options_atm_iv_z30": _z_score(summary.atm_iv, iv_window),
                        "options_skew_z30": _z_score(summary.skew_iv, skew_window),
                        "options_volume_log": math.log1p(summary.total_contracts),
                    },
                )
            )
        output[symbol] = tuple(points)
    return output


def _asof(
    series: Sequence[tuple[int, Mapping[str, float]]],
    timestamp: int,
) -> Mapping[str, float] | None:
    position = bisect_right([row[0] for row in series], timestamp) - 1
    return None if position < 0 else series[position][1]


def _weighted_mean(values: Sequence[tuple[float, float]]) -> float:
    total = sum(weight for _, weight in values)
    if total <= 0.0:
        return math.nan
    return sum(value * weight for value, weight in values) / total


def _z_score(value: float, window: np.ndarray) -> float:
    std = float(np.std(window))
    return (value - float(np.mean(window))) / max(std, 1e-9)


def _read_url(url: str, *, attempts: int = 6) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "WaveMind-Crypto-Research/0.3"}
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception:
            if attempt + 1 >= attempts:
                raise
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise RuntimeError("unreachable")


def _midnight(day: date) -> int:
    return int(
        datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    )


def _days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download fingerprinted Deribit historical option-trade samples."
    )
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--sample-count", type=int, default=250)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = download_options_dataset(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        sample_count=args.sample_count,
        workers=args.workers,
        cache_dir=args.cache_dir,
    )
    save_options_dataset(args.output, dataset)
    print(
        f"Wrote {args.output}: summaries={len(dataset.summaries)}, "
        f"missing={len(dataset.missing_days)}, sample_count={dataset.sample_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
