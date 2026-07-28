# WaveField Predictability Map

This report separates three hypotheses instead of treating all market
prediction as the same task. The protocol was frozen in commit `aad6305` before
the `holdout3` and `holdout4` universes were evaluated.

All final rows are real, non-overlapping UTC days from 2025-2026. The base model
is trained before 2024, its probability threshold is calibrated on 2024-H1,
and its model family is selected on 2024-H2.

| target | universe | independent days | accuracy | balanced accuracy | AUC / Wilson | verdict |
|---|---|---:|---:|---:|---:|---|
| market direction | base 8 | 514 | 50.6% | 49.9% | AUC 0.514 | rejected |
| relative-strength spread | base 8 | 514 | 46.1% | n/a | Wilson 41.8% | rejected |
| high dispersion | base 8 | 514 | 83.1% | 65.2% | AUC 0.738 | rejected |
| high dispersion | holdout3 | 514 | 53.5% | 55.4% | AUC 0.629 | rejected |
| high dispersion | holdout4 | 514 | 67.7% | 61.1% | AUC 0.678 | rejected |

The base high-dispersion row must not be read as an 83.1% general forecasting
claim. The event becomes rare in the final base period, so an always-negative
majority rule reaches 85.4% raw accuracy while having only 50% balanced
accuracy. The field hybrid detects part of the minority regime, but its
worst-year balanced accuracy is 56.7% and neither asset-disjoint replication
passes the frozen gate.

The useful conclusion is narrower: topology-aware WaveField features contain
some information about future cross-asset dispersion, especially in
`holdout4`, but the effect is not yet stable enough for admission. Direction
and daily relative-strength hypotheses remain near chance.
