# WaveMind Crypto Relationship Report

Research-only relationship mining over historical OHLCV windows. This is not financial advice.

## Scenario

- windows: 2049
- global avg future return: -10.44 bps
- global large-move rate: 0.713
- min support: 30
- pairwise: True

## Top Positive Relationships

| relationship | support | lift bps | avg return bps | up | down | large move |
|---|---:|---:|---:|---:|---:|---:|
| rsi_bucket=neutral & trend=up | 516 | 61.79 | 51.35 | 0.516 | 0.380 | 0.727 |
| bollinger_bucket=middle & rsi_bucket=neutral | 1021 | 41.47 | 31.03 | 0.491 | 0.382 | 0.703 |
| close_position_bucket=middle & trend=up | 287 | 71.66 | 61.22 | 0.544 | 0.348 | 0.728 |
| macd_bucket=up & rsi_bucket=neutral | 467 | 52.94 | 42.50 | 0.493 | 0.411 | 0.764 |
| rsi_bucket=neutral | 1185 | 31.77 | 21.33 | 0.467 | 0.408 | 0.709 |
| rsi_bucket=neutral & volatility_bucket=high | 1185 | 31.77 | 21.33 | 0.467 | 0.408 | 0.709 |
| bollinger_bucket=middle & trend=up | 653 | 41.65 | 31.21 | 0.524 | 0.375 | 0.720 |
| drawdown_bucket=deep & rsi_bucket=neutral | 1175 | 30.74 | 20.30 | 0.466 | 0.409 | 0.707 |
| close_position_bucket=near_low & rsi_bucket=neutral | 328 | 50.25 | 39.81 | 0.524 | 0.360 | 0.729 |
| rsi_bucket=neutral & volume_bucket=quiet | 671 | 34.30 | 23.86 | 0.471 | 0.405 | 0.708 |
| close_position_bucket=near_low & volume_bucket=quiet | 394 | 44.69 | 34.25 | 0.536 | 0.343 | 0.734 |
| trend=up & volume_bucket=quiet | 478 | 39.30 | 28.86 | 0.517 | 0.379 | 0.720 |

## Top Negative Relationships

| relationship | support | lift bps | avg return bps | up | down | large move |
|---|---:|---:|---:|---:|---:|---:|
| bollinger_bucket=upper_band & drawdown_bucket=deep | 257 | -90.69 | -101.13 | 0.233 | 0.646 | 0.739 |
| macd_bucket=up & rsi_bucket=overbought | 365 | -75.34 | -85.78 | 0.329 | 0.578 | 0.762 |
| drawdown_bucket=deep & rsi_bucket=overbought | 401 | -71.67 | -82.11 | 0.314 | 0.561 | 0.716 |
| rsi_bucket=overbought | 412 | -68.94 | -79.38 | 0.316 | 0.563 | 0.716 |
| rsi_bucket=overbought & volatility_bucket=high | 412 | -68.94 | -79.38 | 0.316 | 0.563 | 0.716 |
| bollinger_bucket=upper_band & macd_bucket=up | 236 | -89.81 | -100.26 | 0.242 | 0.657 | 0.763 |
| bollinger_bucket=upper_band & recent_trend=up | 264 | -84.44 | -94.88 | 0.242 | 0.640 | 0.735 |
| bollinger_bucket=upper_band | 267 | -83.89 | -94.34 | 0.243 | 0.640 | 0.738 |
| bollinger_bucket=upper_band & volatility_bucket=high | 267 | -83.89 | -94.34 | 0.243 | 0.640 | 0.738 |
| bollinger_bucket=upper_band & rsi_bucket=overbought | 191 | -89.79 | -100.23 | 0.251 | 0.644 | 0.759 |
| close_position_bucket=near_high & rsi_bucket=overbought | 310 | -70.26 | -80.70 | 0.332 | 0.574 | 0.755 |
| rsi_bucket=oversold & volume_bucket=expanded | 142 | -101.05 | -111.49 | 0.324 | 0.542 | 0.718 |

## Top Large-Move Relationships

| relationship | support | lift bps | avg return bps | up | down | large move |
|---|---:|---:|---:|---:|---:|---:|
| recent_trend=down & trend=flat | 33 | 44.89 | 34.45 | 0.515 | 0.394 | 0.879 |
| close_position_bucket=middle & macd_bucket=up | 271 | 36.79 | 26.35 | 0.472 | 0.446 | 0.827 |
| bollinger_bucket=upper_band & volume_bucket=expanded | 141 | -76.70 | -87.14 | 0.291 | 0.631 | 0.801 |
| bollinger_bucket=lower_band & rsi_bucket=neutral | 88 | 6.27 | -4.17 | 0.398 | 0.523 | 0.795 |
| macd_bucket=up & trend=down | 145 | -46.62 | -57.06 | 0.310 | 0.579 | 0.793 |
| macd_bucket=up & recent_trend=down | 269 | 33.65 | 23.21 | 0.461 | 0.450 | 0.788 |
| bollinger_bucket=lower_band & volume_bucket=quiet | 103 | 35.92 | 25.48 | 0.515 | 0.369 | 0.786 |
| macd_bucket=up & volume_bucket=quiet | 422 | 16.48 | 6.04 | 0.455 | 0.448 | 0.780 |
| recent_trend=up & volume_bucket=expanded | 272 | -27.64 | -38.08 | 0.393 | 0.511 | 0.776 |
| macd_bucket=up & volume_bucket=expanded | 247 | -29.98 | -40.42 | 0.397 | 0.526 | 0.773 |
| close_position_bucket=near_high & volume_bucket=expanded | 189 | -37.33 | -47.77 | 0.386 | 0.540 | 0.772 |
| recent_trend=down & volume_bucket=quiet | 496 | 26.01 | 15.57 | 0.486 | 0.409 | 0.770 |
