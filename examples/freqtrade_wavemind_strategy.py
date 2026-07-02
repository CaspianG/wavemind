from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from wavemind import WaveMind

try:
    from freqtrade.strategy import IStrategy
except ImportError:
    IStrategy = object  # type: ignore[misc,assignment]


class WaveMindRegimeMemory:
    """Small dry-run helper for using WaveMind as a market-regime memory layer."""

    def __init__(self, db_path: str | Path = "wavemind-freqtrade.sqlite3"):
        self.memory = WaveMind(
            db_path=db_path,
            index_kind="numpy",
            score_threshold=0.0,
            vector_weight=0.72,
            field_weight=0.08,
            priority_weight=0.18,
            lexical_weight=0.16,
            rerank_k=24,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )

    def remember_candle(self, pair: str, timeframe: str, row: pd.Series, future_return_bps: float | None = None) -> None:
        direction = "flat"
        if future_return_bps is not None and future_return_bps > 30:
            direction = "up"
        elif future_return_bps is not None and future_return_bps < -30:
            direction = "down"
        text = self._row_text(pair, timeframe, row)
        if future_return_bps is not None:
            text += f" | future_direction {direction} | future_return_bps {future_return_bps:.1f}"
        self.memory.remember(
            text,
            namespace=f"freqtrade:{pair}:{timeframe}",
            tags=("crypto", pair, timeframe, direction),
            metadata={
                "pair": pair,
                "timeframe": timeframe,
                "direction": direction,
                "future_return_bps": float(future_return_bps or 0.0),
            },
            priority=1.0 + min(4.0, abs(float(future_return_bps or 0.0)) / 45.0),
        )

    def similar_regimes(self, pair: str, timeframe: str, row: pd.Series, top_k: int = 3) -> list[dict[str, Any]]:
        results = self.memory.query(
            self._row_text(pair, timeframe, row),
            namespace=f"freqtrade:{pair}:{timeframe}",
            top_k=top_k,
        )
        return [
            {
                "score": result.score,
                "direction": result.metadata.get("direction", "flat"),
                "future_return_bps": result.metadata.get("future_return_bps", 0.0),
                "text": result.text,
            }
            for result in results
        ]

    @staticmethod
    def _row_text(pair: str, timeframe: str, row: pd.Series) -> str:
        rsi = float(row.get("rsi", 50.0))
        close = float(row.get("close", 0.0))
        volume = float(row.get("volume", 0.0))
        ema_fast = float(row.get("ema_fast", close))
        ema_slow = float(row.get("ema_slow", close))
        trend = "up" if ema_fast > ema_slow else "down" if ema_fast < ema_slow else "flat"
        rsi_bucket = "oversold" if rsi < 35 else "overbought" if rsi > 65 else "neutral"
        return (
            f"asset crypto | pair {pair} | timeframe {timeframe} | trend {trend} | "
            f"rsi_bucket {rsi_bucket} | rsi {rsi:.1f} | close {close:.8f} | volume {volume:.2f}"
        )


class WaveMindDryRunStrategy(IStrategy):  # type: ignore[misc,valid-type]
    """
    Freqtrade scaffold: use in dry-run/backtest first.

    This is intentionally not a profitable strategy claim. It shows where to wire
    WaveMind as a feature/regime-memory layer inside a Freqtrade strategy.
    """

    timeframe = "1h"
    minimal_roi = {"0": 0.02}
    stoploss = -0.05
    can_short = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if IStrategy is not object:
            super().__init__(config or {})
        self.regime_memory = WaveMindRegimeMemory()

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        dataframe = dataframe.copy()
        dataframe["ema_fast"] = dataframe["close"].ewm(span=12, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=26, adjust=False).mean()
        dataframe["rsi"] = _rsi(dataframe["close"], period=14)
        pair = metadata.get("pair", "UNKNOWN/USDT")
        scores = []
        for _, row in dataframe.tail(200).iterrows():
            analogues = self.regime_memory.similar_regimes(pair, self.timeframe, row, top_k=3)
            expected = sum(float(item["future_return_bps"]) for item in analogues) / max(len(analogues), 1)
            scores.append(expected)
        dataframe.loc[dataframe.tail(len(scores)).index, "wavemind_expected_bps"] = scores
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        dataframe = dataframe.copy()
        dataframe["enter_long"] = 0
        dataframe.loc[
            (dataframe["wavemind_expected_bps"].fillna(0) > 30)
            & (dataframe["ema_fast"] > dataframe["ema_slow"]),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict[str, Any]) -> pd.DataFrame:
        dataframe = dataframe.copy()
        dataframe["exit_long"] = 0
        dataframe.loc[dataframe["wavemind_expected_bps"].fillna(0) < -20, "exit_long"] = 1
        return dataframe


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))
