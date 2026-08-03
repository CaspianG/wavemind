# WaveMind Crypto Prediction Interval Benchmark

Real-OHLCV walk-forward evaluation of adaptive conformal price ranges. Lower interval score is better. This is research evidence, not financial advice.

Nominal coverage: `80%`.

| engine | queries | coverage | mean width | interval score | center MAE | directional signals | signal accuracy | score vs zero |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Zero-return adaptive conformal | 8640 | 0.786 | 1499.2 bps | 2074.8 bps | 367.5 bps | 0 (0.0%) | n/a | +0.0% |
| Historical-median adaptive conformal | 8640 | 0.770 | 1527.1 bps | 2126.3 bps | 379.4 bps | 0 (0.0%) | n/a | -2.5% |
| WaveMind field adaptive conformal | 8640 | 0.786 | 1561.6 bps | 2157.2 bps | 376.8 bps | 3 (0.0%) | 0.000 | -4.0% |
| WaveMind risk-field adaptive conformal | 8640 | 0.791 | 1333.1 bps | 1902.3 bps | 367.5 bps | 0 (0.0%) | n/a | +8.3% |

## By Timeframe

| engine | timeframe | queries | coverage | mean width | interval score | score vs zero |
|---|---|---:|---:|---:|---:|---:|
| Zero-return adaptive conformal | 1d | 2880 | 0.822 | 2975.6 bps | 3902.2 bps | +0.0% |
| Historical-median adaptive conformal | 1d | 2880 | 0.825 | 3012.3 bps | 3917.8 bps | -0.4% |
| WaveMind field adaptive conformal | 1d | 2880 | 0.829 | 3031.7 bps | 3915.6 bps | -0.3% |
| WaveMind risk-field adaptive conformal | 1d | 2880 | 0.833 | 2467.6 bps | 3310.4 bps | +15.2% |
| Zero-return adaptive conformal | 1h | 2880 | 0.707 | 684.9 bps | 1216.7 bps | +0.0% |
| Historical-median adaptive conformal | 1h | 2880 | 0.656 | 728.3 bps | 1324.7 bps | -8.9% |
| WaveMind field adaptive conformal | 1h | 2880 | 0.727 | 819.3 bps | 1373.9 bps | -12.9% |
| WaveMind risk-field adaptive conformal | 1h | 2880 | 0.721 | 762.0 bps | 1313.2 bps | -7.9% |
| Zero-return adaptive conformal | 4h | 2880 | 0.831 | 837.2 bps | 1105.6 bps | +0.0% |
| Historical-median adaptive conformal | 4h | 2880 | 0.828 | 840.7 bps | 1136.4 bps | -2.8% |
| WaveMind field adaptive conformal | 4h | 2880 | 0.801 | 833.9 bps | 1182.2 bps | -6.9% |
| WaveMind risk-field adaptive conformal | 4h | 2880 | 0.819 | 769.7 bps | 1083.2 bps | +2.0% |

## Interpretation

- The center estimate is not presented as a precise future price.
- The range is calibrated on matured errors before each test fold.
- A directional signal exists only when the entire interval is above or below zero.
- Wide ranges are an honest result when the market state does not support precision.
