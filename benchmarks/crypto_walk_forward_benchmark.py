from __future__ import annotations

import argparse
import html
import json
import math
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.crypto_ohlcv import (  # noqa: E402
    OHLCVBar,
    OHLCVWindow,
    fetch_ohlcv_ccxt,
    generate_synthetic_ohlcv,
    load_ohlcv_csv,
    make_ohlcv_windows,
    window_to_text,
)
from wavemind import WaveMind  # noqa: E402
from wavemind.encoders import TextVectorEncoder, create_text_encoder  # noqa: E402


@dataclass(frozen=True)
class MarketDataset:
    symbol: str
    timeframe: str
    bars: list[OHLCVBar]
    windows: list[OHLCVWindow]


@dataclass(frozen=True)
class AnalogueMatch:
    id: str
    score: float
    direction: str
    future_return_bps: float
    start_time: str
    end_time: str
    text: str


@dataclass(frozen=True)
class Prediction:
    direction: str
    expected_return_bps: float
    latency_ms: float
    analogues: list[AnalogueMatch]


@dataclass(frozen=True)
class EventMetric:
    engine: str
    symbol: str
    timeframe: str
    query_id: str
    actual_direction: str
    predicted_direction: str
    actual_return_bps: float
    predicted_return_bps: float
    direction_at_1: float
    direction_at_3: float
    abs_return_error_bps: float
    net_return_bps: float
    latency_ms: float


class MarketEngine:
    name = "engine"

    def add(self, window: OHLCVWindow) -> None:
        raise NotImplementedError

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        raise NotImplementedError

    def close(self) -> None:
        return None


class StaticKnnEngine(MarketEngine):
    name = "Static kNN"

    def __init__(self, encoder: TextVectorEncoder):
        self.encoder = encoder
        self.records: list[OHLCVWindow] = []
        self.texts: list[str] = []
        self.vectors = np.zeros((0, encoder.vector_dim), dtype=np.float32)

    def add(self, window: OHLCVWindow) -> None:
        text = window_to_text(window, include_outcome=True)
        vector = self.encoder.encode_vector(text)
        self.records.append(window)
        self.texts.append(text)
        self.vectors = np.vstack([self.vectors, vector.reshape(1, -1)])

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = self.encoder.encode_vector(window_to_text(window, include_outcome=False))
        scores = self.vectors @ query_vector
        order = np.argsort(scores)[::-1][:top_k]
        latency = (time.perf_counter() - started) * 1000.0
        analogues = [
            _analogue_from_window(self.records[int(index)], self.texts[int(index)], float(scores[int(index)]))
            for index in order
        ]
        top = analogues[0]
        return Prediction(
            direction=top.direction,
            expected_return_bps=top.future_return_bps,
            latency_ms=latency,
            analogues=analogues,
        )


class WaveMindEngine(MarketEngine):
    name = "WaveMind"

    def __init__(self, encoder: TextVectorEncoder, *, symbol: str, timeframe: str, temp_root: Path):
        self.namespace = f"crypto:{symbol}:{timeframe}"
        self.temp_root = temp_root
        self.memory = WaveMind(
            db_path=temp_root / f"{symbol.replace('/', '')}_{timeframe}.sqlite3",
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            vector_weight=0.72,
            field_weight=0.08,
            priority_weight=0.18,
            lexical_weight=0.16,
            rerank_k=32,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )

    def add(self, window: OHLCVWindow) -> None:
        priority = 1.0 + min(4.0, abs(window.future_return_bps) / 45.0)
        self.memory.remember(
            window_to_text(window, include_outcome=True),
            namespace=self.namespace,
            tags=("crypto", window.symbol, window.timeframe, window.direction),
            priority=priority,
            metadata=_window_metadata(window),
        )

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        results = self.memory.query(
            window_to_text(window, include_outcome=False),
            namespace=self.namespace,
            top_k=top_k,
        )
        latency = (time.perf_counter() - started) * 1000.0
        analogues = [
            AnalogueMatch(
                id=str(result.metadata.get("window_id", result.id)),
                score=float(result.score),
                direction=str(result.metadata.get("direction", "flat")),
                future_return_bps=float(result.metadata.get("future_return_bps", 0.0)),
                start_time=str(result.metadata.get("start_time", "")),
                end_time=str(result.metadata.get("end_time", "")),
                text=result.text,
            )
            for result in results
        ]
        if not analogues:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=latency, analogues=[])
        top = analogues[0]
        return Prediction(
            direction=top.direction,
            expected_return_bps=top.future_return_bps,
            latency_ms=latency,
            analogues=analogues,
        )

    def close(self) -> None:
        self.memory.close()


class NaiveEngine(MarketEngine):
    name = "Naive last-regime"

    def __init__(self):
        self.records: list[OHLCVWindow] = []

    def add(self, window: OHLCVWindow) -> None:
        self.records.append(window)

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        latest = self.records[-1]
        latency = (time.perf_counter() - started) * 1000.0
        analogue = _analogue_from_window(latest, window_to_text(latest, include_outcome=True), score=1.0)
        return Prediction(
            direction=latest.direction,
            expected_return_bps=latest.future_return_bps,
            latency_ms=latency,
            analogues=[analogue],
        )


class TaRulesEngine(MarketEngine):
    name = "TA rules"

    def add(self, window: OHLCVWindow) -> None:
        return None

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        features = window.features
        rsi = float(features["rsi"])
        recent = float(features["recent_return_bps"])
        volume_ratio = float(features["volume_ratio"])
        close_position = float(features["close_position"])
        trend = str(features["trend"])
        if rsi < 35.0 and recent < 0:
            direction = "up"
        elif rsi > 65.0 and recent > 0:
            direction = "down"
        elif trend == "up" and close_position > 0.65 and volume_ratio >= 1.0:
            direction = "up"
        elif trend == "down" and close_position < 0.35 and volume_ratio >= 1.0:
            direction = "down"
        else:
            direction = "flat"
        expected = abs(recent) * 0.55
        if direction == "down":
            expected = -expected
        elif direction == "flat":
            expected = 0.0
        return Prediction(
            direction=direction,
            expected_return_bps=float(expected),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            analogues=[],
        )


class ChromaEngine(StaticKnnEngine):
    name = "Chroma"

    def __init__(self, encoder: TextVectorEncoder):
        self.encoder = encoder
        self.records_by_id: dict[str, tuple[OHLCVWindow, str]] = {}
        try:
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore
        except ImportError as exc:
            raise RuntimeError("chromadb is not installed; install the bench extra") from exc
        self.client = chromadb.Client(Settings(anonymized_telemetry=False, allow_reset=True, is_persistent=False))
        self.collection = self.client.create_collection(
            name=f"wmcrypto{uuid.uuid4().hex[:12]}",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, window: OHLCVWindow) -> None:
        text = window_to_text(window, include_outcome=True)
        vector = self.encoder.encode_vector(text)
        self.records_by_id[window.id] = (window, text)
        self.collection.add(
            ids=[window.id],
            documents=[text],
            embeddings=[vector.astype(float).tolist()],
            metadatas=[_window_metadata(window)],
        )

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records_by_id:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = self.encoder.encode_vector(window_to_text(window, include_outcome=False))
        response = self.collection.query(
            query_embeddings=[query_vector.astype(float).tolist()],
            n_results=top_k,
        )
        latency = (time.perf_counter() - started) * 1000.0
        ids = response.get("ids", [[]])[0]
        distances = response.get("distances", [[]])[0]
        analogues = []
        for item_id, distance in zip(ids, distances):
            record, text = self.records_by_id[str(item_id)]
            analogues.append(_analogue_from_window(record, text, score=1.0 - float(distance)))
        if not analogues:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=latency, analogues=[])
        top = analogues[0]
        return Prediction(top.direction, top.future_return_bps, latency, analogues)


class QdrantEngine(StaticKnnEngine):
    name = "Qdrant"

    def __init__(self, encoder: TextVectorEncoder):
        self.encoder = encoder
        self.next_id = 1
        self.records_by_point: dict[int, tuple[OHLCVWindow, str]] = {}
        self.collection_name = f"wmcrypto_{uuid.uuid4().hex[:12]}"
        try:
            from qdrant_client import QdrantClient, models  # type: ignore
        except ImportError as exc:
            raise RuntimeError("qdrant-client is not installed; install the bench extra") from exc
        self.models = models
        self.client = QdrantClient(":memory:")
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(size=encoder.vector_dim, distance=models.Distance.COSINE),
        )

    def add(self, window: OHLCVWindow) -> None:
        text = window_to_text(window, include_outcome=True)
        vector = self.encoder.encode_vector(text)
        point_id = self.next_id
        self.next_id += 1
        self.records_by_point[point_id] = (window, text)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                self.models.PointStruct(
                    id=point_id,
                    vector=vector.astype(float).tolist(),
                    payload={"window_id": window.id},
                )
            ],
        )

    def query(self, window: OHLCVWindow, *, top_k: int) -> Prediction:
        started = time.perf_counter()
        if not self.records_by_point:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=0.0, analogues=[])
        query_vector = self.encoder.encode_vector(window_to_text(window, include_outcome=False)).astype(float).tolist()
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
            )
            points = response.points
        else:
            points = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
            )
        latency = (time.perf_counter() - started) * 1000.0
        analogues = []
        for point in points:
            point_id = int(point.id)
            record, text = self.records_by_point[point_id]
            analogues.append(_analogue_from_window(record, text, score=float(point.score)))
        if not analogues:
            return Prediction(direction="flat", expected_return_bps=0.0, latency_ms=latency, analogues=[])
        top = analogues[0]
        return Prediction(top.direction, top.future_return_bps, latency, analogues)


def run_walk_forward(
    *,
    markets: list[MarketDataset],
    engines: Iterable[str],
    train_windows: int = 180,
    test_windows: int = 60,
    top_k: int = 5,
    encoder_kind: str = "hash",
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    analogue_limit: int = 18,
) -> dict:
    engine_keys = _normalize_engines(engines)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    round_trip_cost_bps = 2.0 * (float(fee_bps) + float(slippage_bps))
    all_results = []
    by_market = []
    analogue_samples = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        for engine_key in engine_keys:
            engine_events: list[EventMetric] = []
            skipped_reason: str | None = None
            for market in markets:
                selected_queries = _select_test_windows(
                    market.windows,
                    train_windows=train_windows,
                    test_windows=test_windows,
                )
                try:
                    engine = _create_engine(engine_key, encoder, market=market, temp_root=temp_root)
                except RuntimeError as exc:
                    skipped_reason = str(exc)
                    break
                added_ids: set[str] = set()
                market_events: list[EventMetric] = []
                try:
                    for query_window in selected_queries:
                        _add_mature_history(
                            engine,
                            market.windows,
                            current=query_window,
                            added_ids=added_ids,
                        )
                        prediction = engine.query(query_window, top_k=top_k)
                        event = _event_metric(
                            engine_name=engine.name,
                            window=query_window,
                            prediction=prediction,
                            round_trip_cost_bps=round_trip_cost_bps,
                        )
                        market_events.append(event)
                        if len(analogue_samples) < analogue_limit and prediction.analogues:
                            analogue_samples.append(
                                _analogue_sample(engine.name, query_window, prediction)
                            )
                    engine_events.extend(market_events)
                    by_market.append(_summarize_events(engine.name, market_events, market.symbol, market.timeframe))
                finally:
                    engine.close()
            if skipped_reason is not None:
                all_results.append(
                    {
                        "engine": _engine_display_name(engine_key),
                        "skipped": True,
                        "skip_reason": skipped_reason,
                    }
                )
            else:
                all_results.append(_summarize_events(_engine_display_name(engine_key), engine_events))

    return {
        "scenario": {
            "name": "crypto_walk_forward",
            "dataset_markets": [
                {
                    "symbol": market.symbol,
                    "timeframe": market.timeframe,
                    "bars": len(market.bars),
                    "windows": len(market.windows),
                }
                for market in markets
            ],
            "train_windows": train_windows,
            "test_windows": test_windows,
            "top_k": top_k,
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "round_trip_cost_bps": round_trip_cost_bps,
            "note": "Research walk-forward retrieval benchmark. This is not financial advice or a profit claim.",
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
        },
        "results": all_results,
        "by_market": by_market,
        "analogue_samples": analogue_samples,
    }


def load_markets_from_args(args: argparse.Namespace) -> list[MarketDataset]:
    markets: list[MarketDataset] = []
    direction_threshold = max(15.0, 2.0 * (float(args.fee_bps) + float(args.slippage_bps)))
    if args.dataset == "synthetic":
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                bars = generate_synthetic_ohlcv(symbol=symbol, timeframe=timeframe, bars=args.bars, seed=args.seed)
                windows = make_ohlcv_windows(
                    bars,
                    symbol=symbol,
                    timeframe=timeframe,
                    window=args.window,
                    horizon=args.horizon,
                    direction_threshold_bps=direction_threshold,
                )
                markets.append(MarketDataset(symbol=symbol, timeframe=timeframe, bars=bars, windows=windows))
        return markets
    if args.dataset == "csv":
        if args.csv is None:
            raise ValueError("--csv is required for --dataset csv")
        if len(args.symbols) != 1 or len(args.timeframes) != 1:
            raise ValueError("--dataset csv expects one --symbols value and one --timeframes value")
        bars = load_ohlcv_csv(args.csv)
        windows = make_ohlcv_windows(
            bars,
            symbol=args.symbols[0],
            timeframe=args.timeframes[0],
            window=args.window,
            horizon=args.horizon,
            direction_threshold_bps=direction_threshold,
        )
        return [MarketDataset(symbol=args.symbols[0], timeframe=args.timeframes[0], bars=bars, windows=windows)]
    if args.dataset == "ccxt":
        if args.exchange is None:
            raise ValueError("--exchange is required for --dataset ccxt")
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                bars = fetch_ohlcv_ccxt(
                    exchange_id=args.exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=args.bars,
                )
                windows = make_ohlcv_windows(
                    bars,
                    symbol=symbol,
                    timeframe=timeframe,
                    window=args.window,
                    horizon=args.horizon,
                    direction_threshold_bps=direction_threshold,
                )
                markets.append(MarketDataset(symbol=symbol, timeframe=timeframe, bars=bars, windows=windows))
        return markets
    raise ValueError(f"Unknown dataset: {args.dataset}")


def write_analogue_html(payload: Mapping[str, object], path: str | Path) -> None:
    rows = []
    for sample in payload.get("analogue_samples", []):  # type: ignore[union-attr]
        query = sample["query"]  # type: ignore[index]
        analogues = sample["analogues"]  # type: ignore[index]
        analogue_rows = "".join(
            "<tr>"
            f"<td>{html.escape(match['start_time'])}</td>"
            f"<td>{html.escape(match['direction'])}</td>"
            f"<td>{float(match['future_return_bps']):.1f}</td>"
            f"<td>{float(match['score']):.3f}</td>"
            "</tr>"
            for match in analogues
        )
        rows.append(
            "<section class='card'>"
            f"<h2>{html.escape(sample['engine'])} - {html.escape(query['symbol'])} {html.escape(query['timeframe'])}</h2>"
            f"<p class='muted'>Current window: {html.escape(query['start_time'])} -> {html.escape(query['end_time'])}</p>"
            f"<p>Actual next move: <strong>{html.escape(query['direction'])}</strong> "
            f"({float(query['future_return_bps']):.1f} bps)</p>"
            "<table><thead><tr><th>Historical window</th><th>Next move</th><th>Return bps</th><th>Score</th></tr></thead>"
            f"<tbody>{analogue_rows}</tbody></table>"
            "</section>"
        )
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>WaveMind Crypto Analogue Explorer</title>"
        "<style>"
        "body{font-family:Inter,Arial,sans-serif;margin:32px;background:#f7f7f5;color:#111}"
        "h1{font-size:28px;margin-bottom:4px}.muted{color:#666}.card{background:white;border:1px solid #ddd;"
        "border-radius:8px;padding:18px;margin:18px 0;box-shadow:0 1px 2px #0001}"
        "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #eee;"
        "padding:8px;text-align:left}th{background:#fafafa}"
        "</style></head><body>"
        "<h1>WaveMind Crypto Analogue Explorer</h1>"
        "<p class='muted'>Research view: current market windows and similar historical windows. Not financial advice.</p>"
        f"{''.join(rows) if rows else '<p>No analogue samples were produced.</p>'}"
        "</body></html>"
    )
    html_path = Path(path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(document, encoding="utf-8")


def print_table(payload: Mapping[str, object]) -> None:
    print("| engine | direction@1 | direction@3 | avg net bps | hit rate | avg latency | queries |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for result in payload["results"]:  # type: ignore[index]
        if result.get("skipped"):  # type: ignore[union-attr]
            print(f"| {result['engine']} | skipped | skipped | skipped | skipped | skipped | 0 |")
            continue
        print(
            f"| {result['engine']} | "
            f"{result['direction_accuracy_at_1']:.3f} | "
            f"{result['direction_accuracy_at_3']:.3f} | "
            f"{result['avg_net_return_bps']:.2f} | "
            f"{result['hit_rate_after_costs']:.3f} | "
            f"{result['avg_latency_ms']:.2f} ms | "
            f"{result['queries']} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["synthetic", "csv", "ccxt"], default="synthetic")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h", "1d"])
    parser.add_argument("--engines", nargs="+", default=["wavemind", "static", "chroma", "qdrant", "naive", "ta"])
    parser.add_argument("--bars", type=int, default=420)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--train-windows", type=int, default=180)
    parser.add_argument("--test-windows", type=int, default=60)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_walk_forward_results.json"))
    parser.add_argument("--analogue-html", type=Path, default=Path("benchmarks/crypto_analogue_explorer.html"))
    args = parser.parse_args()

    markets = load_markets_from_args(args)
    payload = run_walk_forward(
        markets=markets,
        engines=args.engines,
        train_windows=args.train_windows,
        test_windows=args.test_windows,
        top_k=args.top_k,
        encoder_kind=args.encoder,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_analogue_html(payload, args.analogue_html)
    print_table(payload)
    print(f"\nWrote {args.output}")
    print(f"Wrote {args.analogue_html}")
    return 0


def _normalize_engines(engines: Iterable[str]) -> list[str]:
    normalized = []
    for engine in engines:
        key = engine.lower()
        if key == "all":
            normalized.extend(["wavemind", "static", "chroma", "qdrant", "naive", "ta"])
        else:
            normalized.append(key)
    valid = {"wavemind", "static", "static-knn", "chroma", "qdrant", "naive", "ta", "ta-rules"}
    unknown = [engine for engine in normalized if engine not in valid]
    if unknown:
        raise ValueError(f"Unknown engine(s): {', '.join(unknown)}")
    return normalized


def _create_engine(
    engine_key: str,
    encoder: TextVectorEncoder,
    *,
    market: MarketDataset,
    temp_root: Path,
) -> MarketEngine:
    if engine_key == "wavemind":
        return WaveMindEngine(encoder, symbol=market.symbol, timeframe=market.timeframe, temp_root=temp_root)
    if engine_key in {"static", "static-knn"}:
        return StaticKnnEngine(encoder)
    if engine_key == "chroma":
        return ChromaEngine(encoder)
    if engine_key == "qdrant":
        return QdrantEngine(encoder)
    if engine_key == "naive":
        return NaiveEngine()
    if engine_key in {"ta", "ta-rules"}:
        return TaRulesEngine()
    raise ValueError(f"Unknown engine: {engine_key}")


def _engine_display_name(engine_key: str) -> str:
    return {
        "wavemind": "WaveMind",
        "static": "Static kNN",
        "static-knn": "Static kNN",
        "chroma": "Chroma",
        "qdrant": "Qdrant",
        "naive": "Naive last-regime",
        "ta": "TA rules",
        "ta-rules": "TA rules",
    }[engine_key]


def _select_test_windows(
    windows: list[OHLCVWindow],
    *,
    train_windows: int,
    test_windows: int,
) -> list[OHLCVWindow]:
    if train_windows <= 0 or test_windows <= 0:
        raise ValueError("train_windows and test_windows must be positive")
    start = train_windows
    end = start + test_windows
    if len(windows) < end:
        raise ValueError(
            f"not enough windows: need at least {end}, got {len(windows)}. "
            "Increase --bars or reduce train/test windows."
        )
    return windows[start:end]


def _add_mature_history(
    engine: MarketEngine,
    windows: list[OHLCVWindow],
    *,
    current: OHLCVWindow,
    added_ids: set[str],
) -> None:
    for historical in windows:
        if historical.id in added_ids:
            continue
        if historical.start_ts >= current.start_ts:
            break
        if historical.future_end_ts <= current.end_ts:
            engine.add(historical)
            added_ids.add(historical.id)


def _event_metric(
    *,
    engine_name: str,
    window: OHLCVWindow,
    prediction: Prediction,
    round_trip_cost_bps: float,
) -> EventMetric:
    direction_at_1 = 1.0 if prediction.direction == window.direction else 0.0
    top3_directions = [match.direction for match in prediction.analogues[:3]]
    if not top3_directions:
        top3_directions = [prediction.direction]
    direction_at_3 = 1.0 if window.direction in top3_directions else 0.0
    net = _net_return_bps(
        predicted_direction=prediction.direction,
        actual_return_bps=window.future_return_bps,
        round_trip_cost_bps=round_trip_cost_bps,
    )
    return EventMetric(
        engine=engine_name,
        symbol=window.symbol,
        timeframe=window.timeframe,
        query_id=window.id,
        actual_direction=window.direction,
        predicted_direction=prediction.direction,
        actual_return_bps=float(window.future_return_bps),
        predicted_return_bps=float(prediction.expected_return_bps),
        direction_at_1=direction_at_1,
        direction_at_3=direction_at_3,
        abs_return_error_bps=abs(float(prediction.expected_return_bps) - float(window.future_return_bps)),
        net_return_bps=net,
        latency_ms=float(prediction.latency_ms),
    )


def _net_return_bps(
    *,
    predicted_direction: str,
    actual_return_bps: float,
    round_trip_cost_bps: float,
) -> float:
    if predicted_direction == "up":
        return float(actual_return_bps) - round_trip_cost_bps
    if predicted_direction == "down":
        return -float(actual_return_bps) - round_trip_cost_bps
    return 0.0


def _summarize_events(
    engine_name: str,
    events: list[EventMetric],
    symbol: str | None = None,
    timeframe: str | None = None,
) -> dict:
    if not events:
        return {
            "engine": engine_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "queries": 0,
            "direction_accuracy_at_1": 0.0,
            "direction_accuracy_at_3": 0.0,
            "mean_abs_return_error_bps": math.inf,
            "avg_net_return_bps": 0.0,
            "hit_rate_after_costs": 0.0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
        }
    latencies = sorted(event.latency_ms for event in events)
    p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
    payload = {
        "engine": engine_name,
        "queries": len(events),
        "direction_accuracy_at_1": statistics.mean(event.direction_at_1 for event in events),
        "direction_accuracy_at_3": statistics.mean(event.direction_at_3 for event in events),
        "mean_abs_return_error_bps": statistics.mean(event.abs_return_error_bps for event in events),
        "avg_net_return_bps": statistics.mean(event.net_return_bps for event in events),
        "hit_rate_after_costs": statistics.mean(1.0 if event.net_return_bps > 0 else 0.0 for event in events),
        "avg_latency_ms": statistics.mean(event.latency_ms for event in events),
        "p95_latency_ms": latencies[p95_index],
    }
    if symbol is not None:
        payload["symbol"] = symbol
    if timeframe is not None:
        payload["timeframe"] = timeframe
    return payload


def _analogue_from_window(window: OHLCVWindow, text: str, score: float) -> AnalogueMatch:
    return AnalogueMatch(
        id=window.id,
        score=float(score),
        direction=window.direction,
        future_return_bps=float(window.future_return_bps),
        start_time=window.start_time,
        end_time=window.end_time,
        text=text,
    )


def _window_metadata(window: OHLCVWindow) -> dict[str, str | int | float]:
    return {
        "window_id": window.id,
        "symbol": window.symbol,
        "timeframe": window.timeframe,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "direction": window.direction,
        "future_return_bps": float(window.future_return_bps),
        "index": int(window.index),
    }


def _analogue_sample(engine_name: str, window: OHLCVWindow, prediction: Prediction) -> dict:
    return {
        "engine": engine_name,
        "query": {
            "id": window.id,
            "symbol": window.symbol,
            "timeframe": window.timeframe,
            "start_time": window.start_time,
            "end_time": window.end_time,
            "direction": window.direction,
            "future_return_bps": float(window.future_return_bps),
            "text": window_to_text(window, include_outcome=False),
        },
        "prediction": {
            "direction": prediction.direction,
            "expected_return_bps": float(prediction.expected_return_bps),
            "latency_ms": float(prediction.latency_ms),
        },
        "analogues": [asdict(match) for match in prediction.analogues[:5]],
    }


if __name__ == "__main__":
    raise SystemExit(main())
