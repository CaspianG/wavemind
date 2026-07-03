# WaveMind Crypto Relationship Validation

Train/test validation for mined OHLCV relationships. This is not financial advice.

## Summary

- validated relationships: 74
- sign preservation rate: 0.622
- avg signed test lift: 18.32 bps
- median signed test lift: 15.29 bps

## Top Aggregated Relationships

| relationship | expected | occurrences | sign preserved | avg signed test lift | test support |
|---|---|---:|---:|---:|---:|
| close_position_bucket=near_high & rsi_bucket=overbought | negative | 3 | 1.000 | 138.81 | 84 |
| macd_bucket=up & rsi_bucket=overbought | negative | 3 | 1.000 | 133.12 | 89 |
| rsi_bucket=neutral & trend=up | positive | 2 | 1.000 | 62.31 | 93 |
| bollinger_bucket=middle & rsi_bucket=neutral | positive | 4 | 0.750 | 29.68 | 346 |
| rsi_bucket=overbought | negative | 4 | 0.750 | 43.39 | 117 |
| rsi_bucket=overbought & volatility_bucket=high | negative | 4 | 0.750 | 43.39 | 117 |
| bollinger_bucket=upper_band & macd_bucket=up | negative | 2 | 0.500 | 76.00 | 38 |
| bollinger_bucket=upper_band & drawdown_bucket=deep | negative | 2 | 0.500 | 70.39 | 40 |
| bollinger_bucket=upper_band & recent_trend=up | negative | 2 | 0.500 | 70.39 | 40 |
| bollinger_bucket=upper_band | negative | 2 | 0.500 | 70.39 | 40 |
| bollinger_bucket=upper_band & volatility_bucket=high | negative | 2 | 0.500 | 70.39 | 40 |
| drawdown_bucket=deep & rsi_bucket=neutral | positive | 2 | 1.000 | 30.56 | 209 |

## Top Out-Of-Sample Relationship Events

| relationship | expected | train lift | test lift | signed test lift | test support |
|---|---|---:|---:|---:|---:|
| close_position_bucket=near_high & rsi_bucket=overbought | negative | -103.28 | -220.46 | 220.46 | 13 |
| macd_bucket=up & rsi_bucket=overbought | negative | -96.80 | -199.85 | 199.85 | 14 |
| bollinger_bucket=upper_band & drawdown_bucket=deep | negative | -84.76 | -175.55 | 175.55 | 17 |
| bollinger_bucket=upper_band & recent_trend=up | negative | -78.27 | -175.55 | 175.55 | 17 |
| bollinger_bucket=upper_band | negative | -77.79 | -175.55 | 175.55 | 17 |
| bollinger_bucket=upper_band & volatility_bucket=high | negative | -77.79 | -175.55 | 175.55 | 17 |
| bollinger_bucket=upper_band & macd_bucket=up | negative | -83.38 | -186.76 | 186.76 | 15 |
| drawdown_bucket=deep & rsi_bucket=overbought | negative | -96.07 | -154.75 | 154.75 | 19 |
| rsi_bucket=overbought | negative | -91.14 | -154.75 | 154.75 | 19 |
| rsi_bucket=overbought & volatility_bucket=high | negative | -91.14 | -154.75 | 154.75 | 19 |
| macd_bucket=up & rsi_bucket=overbought | negative | -71.78 | -167.92 | 167.92 | 16 |
| close_position_bucket=near_high & rsi_bucket=overbought | negative | -66.92 | -164.92 | 164.92 | 13 |

## Failed / Unstable Examples

| relationship | expected | train lift | test lift | signed test lift | test support |
|---|---|---:|---:|---:|---:|
| rsi_bucket=oversold & volume_bucket=quiet | positive | 64.41 | -150.89 | -150.89 | 19 |
| bollinger_bucket=lower_band & rsi_bucket=oversold | positive | 73.38 | -144.06 | -144.06 | 59 |
| recent_trend=down & rsi_bucket=oversold | positive | 58.40 | -133.50 | -133.50 | 89 |
| macd_bucket=down & recent_trend=down | positive | 43.50 | -120.47 | -120.47 | 108 |
| drawdown_bucket=deep & rsi_bucket=overbought | negative | -95.37 | 116.69 | -116.69 | 17 |
| rsi_bucket=overbought | negative | -90.54 | 116.69 | -116.69 | 17 |
| rsi_bucket=overbought & volatility_bucket=high | negative | -90.54 | 116.69 | -116.69 | 17 |
| recent_trend=up & rsi_bucket=overbought | negative | -94.16 | 111.38 | -111.38 | 16 |
| close_position_bucket=near_low & recent_trend=down | positive | 47.19 | -107.67 | -107.67 | 105 |
| close_position_bucket=middle & recent_trend=down | positive | 53.12 | -93.15 | -93.15 | 42 |
| close_position_bucket=middle & trend=up | positive | 90.43 | -83.42 | -83.42 | 34 |
| close_position_bucket=middle & volume_bucket=quiet | positive | 59.10 | -83.20 | -83.20 | 45 |
