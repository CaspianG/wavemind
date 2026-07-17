from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import OHLCVBar, parse_timestamp, timeframe_to_seconds  # noqa: E402


@dataclass(frozen=True)
class DerivativesObservation:
    """A normalized exchange observation, timestamped when it became observable."""

    timestamp: int
    funding_rate: float | None = None
    open_interest_value: float | None = None
    long_short_ratio: float | None = None

    @property
    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class AlignedDerivatives:
    """Latest causally available derivatives state at an OHLCV candle close."""

    observed_until_ts: int
    funding_rate: float
    open_interest_value: float
    long_short_ratio: float
    funding_timestamp: int
    open_interest_timestamp: int
    long_short_timestamp: int


def fetch_derivatives_ccxt(
    *,
    exchange_id: str,
    symbol: str,
    timeframe: str = "1h",
    since: int | None = None,
    limit: int = 1000,
    params: Mapping[str, Any] | None = None,
) -> list[DerivativesObservation]:
    """Fetch three normalized derivatives streams and merge them by publication time.

    The function is intentionally fail-closed. A benchmark that asks for derivatives
    evidence must not silently degrade to an OHLCV-only model when a stream is absent.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    try:
        import ccxt  # type: ignore
    except ImportError as exc:
        raise RuntimeError('Install the crypto extra first: pip install -e ".[crypto]"') from exc
    if not hasattr(ccxt, exchange_id):
        raise ValueError(f"Unknown CCXT exchange: {exchange_id}")

    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    required = {
        "fetchFundingRateHistory": "fetch_funding_rate_history",
        "fetchOpenInterestHistory": "fetch_open_interest_history",
        "fetchLongShortRatioHistory": "fetch_long_short_ratio_history",
    }
    missing = [capability for capability in required if not bool(exchange.has.get(capability))]
    if missing:
        raise RuntimeError(
            f"CCXT exchange {exchange_id!r} does not expose required streams: {', '.join(missing)}"
        )

    since_ms = _timestamp_ms(since) if since is not None else None
    common_params = dict(params or {})
    funding = _fetch_paginated(
        exchange.fetch_funding_rate_history,
        symbol=symbol,
        timeframe=None,
        since_ms=since_ms,
        limit=limit,
        params=common_params,
    )
    open_interest = _fetch_paginated(
        exchange.fetch_open_interest_history,
        symbol=symbol,
        timeframe=timeframe,
        since_ms=since_ms,
        limit=limit,
        params=common_params,
    )
    long_short = _fetch_paginated(
        exchange.fetch_long_short_ratio_history,
        symbol=symbol,
        timeframe=timeframe,
        since_ms=since_ms,
        limit=limit,
        params=common_params,
    )
    if not funding or not open_interest or not long_short:
        counts = (len(funding), len(open_interest), len(long_short))
        raise RuntimeError(
            "Incomplete derivatives history: "
            f"funding={counts[0]}, open_interest={counts[1]}, long_short={counts[2]}"
        )
    return merge_derivatives_history(funding, open_interest, long_short)


def merge_derivatives_history(
    funding_rows: Iterable[Mapping[str, Any]],
    open_interest_rows: Iterable[Mapping[str, Any]],
    long_short_rows: Iterable[Mapping[str, Any]],
) -> list[DerivativesObservation]:
    merged: dict[int, dict[str, float | int | None]] = {}

    def add(rows: Iterable[Mapping[str, Any]], field: str, source_key: str) -> None:
        for row in rows:
            timestamp = _row_timestamp(row)
            if source_key not in row or row[source_key] is None:
                raise ValueError(f"CCXT row at {timestamp} is missing normalized field {source_key!r}")
            merged.setdefault(timestamp, {"timestamp": timestamp})[field] = float(row[source_key])

    add(funding_rows, "funding_rate", "fundingRate")
    add(open_interest_rows, "open_interest_value", "openInterestValue")
    add(long_short_rows, "long_short_ratio", "longShortRatio")
    return [
        DerivativesObservation(
            timestamp=timestamp,
            funding_rate=_optional_float(values.get("funding_rate")),
            open_interest_value=_optional_float(values.get("open_interest_value")),
            long_short_ratio=_optional_float(values.get("long_short_ratio")),
        )
        for timestamp, values in sorted(merged.items())
    ]


def align_derivatives_to_bars(
    bars: Sequence[OHLCVBar],
    observations: Iterable[DerivativesObservation],
    *,
    timeframe: str,
    max_age_seconds: int | None = None,
    require_complete: bool = True,
) -> list[AlignedDerivatives]:
    """Backward as-of join that can never attach future evidence to a candle."""
    if max_age_seconds is not None and max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    rows = sorted(observations, key=lambda item: item.timestamp)
    latest: dict[str, tuple[int, float]] = {}
    cursor = 0
    step = timeframe_to_seconds(timeframe)
    aligned: list[AlignedDerivatives] = []
    for bar in sorted(bars, key=lambda item: item.timestamp):
        cutoff = int(bar.timestamp) + step
        while cursor < len(rows) and rows[cursor].timestamp <= cutoff:
            row = rows[cursor]
            for field in ("funding_rate", "open_interest_value", "long_short_ratio"):
                value = getattr(row, field)
                if value is not None:
                    latest[field] = (int(row.timestamp), float(value))
            cursor += 1
        missing = [
            field
            for field in ("funding_rate", "open_interest_value", "long_short_ratio")
            if field not in latest
        ]
        if missing:
            if require_complete:
                raise ValueError(
                    f"No causal derivatives state for candle close {cutoff}: {', '.join(missing)}"
                )
            continue
        if max_age_seconds is not None:
            stale = [field for field, (timestamp, _) in latest.items() if cutoff - timestamp > max_age_seconds]
            if stale:
                if require_complete:
                    raise ValueError(
                        f"Stale derivatives state for candle close {cutoff}: {', '.join(sorted(stale))}"
                    )
                continue
        funding_ts, funding = latest["funding_rate"]
        open_interest_ts, open_interest = latest["open_interest_value"]
        long_short_ts, long_short = latest["long_short_ratio"]
        aligned.append(
            AlignedDerivatives(
                observed_until_ts=cutoff,
                funding_rate=funding,
                open_interest_value=open_interest,
                long_short_ratio=long_short,
                funding_timestamp=funding_ts,
                open_interest_timestamp=open_interest_ts,
                long_short_timestamp=long_short_ts,
            )
        )
    return aligned


def save_derivatives_csv(path: str | Path, observations: Iterable[DerivativesObservation]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "funding_rate", "open_interest_value", "long_short_ratio"],
        )
        writer.writeheader()
        for row in sorted(observations, key=lambda item: item.timestamp):
            writer.writerow(
                {
                    "timestamp": int(row.timestamp),
                    "funding_rate": _csv_value(row.funding_rate),
                    "open_interest_value": _csv_value(row.open_interest_value),
                    "long_short_ratio": _csv_value(row.long_short_ratio),
                }
            )


def load_derivatives_csv(path: str | Path) -> list[DerivativesObservation]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "funding_rate", "open_interest_value", "long_short_ratio"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError(f"CSV {csv_path} must contain: {', '.join(sorted(required))}")
        rows = [
            DerivativesObservation(
                timestamp=parse_timestamp(row["timestamp"]),
                funding_rate=_parse_optional(row["funding_rate"]),
                open_interest_value=_parse_optional(row["open_interest_value"]),
                long_short_ratio=_parse_optional(row["long_short_ratio"]),
            )
            for row in reader
        ]
    if not rows:
        raise ValueError(f"CSV has no derivatives rows: {csv_path}")
    return sorted(rows, key=lambda item: item.timestamp)


def _fetch_paginated(
    fetcher: Callable[..., list[Mapping[str, Any]]],
    *,
    symbol: str,
    timeframe: str | None,
    since_ms: int | None,
    limit: int,
    params: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    cursor = since_ms
    while len(rows) < limit:
        page_limit = min(100, limit - len(rows))
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "since": cursor,
            "limit": page_limit,
            "params": dict(params),
        }
        if timeframe is not None:
            kwargs["timeframe"] = timeframe
        page = list(fetcher(**kwargs) or [])
        if not page:
            break
        added = 0
        for row in sorted(page, key=_row_timestamp):
            timestamp = _row_timestamp(row)
            if timestamp in seen:
                continue
            rows.append(row)
            seen.add(timestamp)
            added += 1
            if len(rows) >= limit:
                break
        if since_ms is None or added == 0:
            break
        last_timestamp_ms = max(_row_timestamp_ms(row) for row in page)
        next_cursor = (last_timestamp_ms // 1000 + 1) * 1000
        if cursor is not None and next_cursor <= cursor:
            break
        cursor = next_cursor
    return sorted(rows, key=_row_timestamp)[:limit]


def _row_timestamp(row: Mapping[str, Any]) -> int:
    if row.get("timestamp") is None:
        raise ValueError("CCXT derivatives row is missing timestamp")
    return parse_timestamp(row["timestamp"])


def _row_timestamp_ms(row: Mapping[str, Any]) -> int:
    if row.get("timestamp") is None:
        raise ValueError("CCXT derivatives row is missing timestamp")
    value = float(row["timestamp"])
    return int(value) if value >= 10_000_000_000 else int(value * 1000)


def _timestamp_ms(value: int) -> int:
    return int(value) if int(value) >= 10_000_000_000 else int(value) * 1000


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _csv_value(value: float | None) -> str:
    return "" if value is None else f"{float(value):.12g}"


def _parse_optional(value: str | None) -> float | None:
    return None if value is None or not value.strip() else float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch causal crypto derivatives evidence through CCXT.")
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--since", help="UTC ISO timestamp or Unix timestamp")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    since = parse_timestamp(args.since) if args.since else None
    observations = fetch_derivatives_ccxt(
        exchange_id=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        since=since,
        limit=args.limit,
    )
    save_derivatives_csv(args.output, observations)
    print(f"Wrote {len(observations)} observations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
