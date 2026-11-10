# Daily seven-day forecast replay

Use the unchanged current forecast function on daily closed candles. Evaluate
BTC, ETH, SOL, GRAM, XRP, ADA, DOGE, and AVAX from 2026-08-11 until 2026-11-11
(exclusive). A forecast origin is the UTC closing time of its last input candle.
Use at most 800 preceding daily bars, window 32, horizon 7, top-k 5, 10 bps fees
and 5 bps slippage. No parameter search is part of this replay.

- [x] Test prefix isolation, exact seven-day settlement, pending outcomes,
      gaps, flat baselines, aggregation, and equivalence with the live runner.
- [x] Add the replay runner and freeze its protocol before downloading outcomes.
- [x] Download and fingerprint real OKX daily candles; explicitly merge the
      established Binance TON predecessor for GRAM. Retain the raw input snapshot.
- [x] Evaluate every daily origin, then report monthly, asset, observable market
      regime, and seven disjoint weekly-phase results. Compare fixed baselines.
- [x] Verify outputs and prepare evidence for publication in the research branch.
      Two complete computations give identical metrics. Audit all 736 prefixes
      and settlements, and independently reproduce 16 real live-runner calls.
      Explain the measured accuracy and target-price error in the report.

Rolling forecasts overlap and assets share market exposure. Report these
dependencies explicitly. This is a historical replay, not a recovered record of
forecasts actually published during the evaluation period. Keep unsupported
weekly trading admission distinct from research direction estimates.
