from __future__ import annotations

from benchmarks.crypto_market_wave_benchmark import (
    MarketPanel,
    _admitted_70,
    _predict_folds,
    run_market_wave_benchmark,
    summarize_oracle,
    summarize_predictions,
)


def _panels(*, per_fold: int = 52) -> list[MarketPanel]:
    panels = []
    day = 24 * 60 * 60
    for fold in range(5):
        for index in range(per_fold):
            observed = (fold * per_fold + index) * day
            signal = 1.0 if index % 2 else -1.0
            up = signal > 0.0
            panels.append(
                MarketPanel(
                    observed_at=observed,
                    target_at=observed + day,
                    fold_index=fold,
                    features=(signal, signal * 0.5, float(index % 7)),
                    market_up=up,
                    asset_outcomes=(
                        ("BTCUSDT", up),
                        ("ETHUSDT", up),
                        ("SOLUSDT", up),
                    ),
                )
            )
    return panels


def test_predict_folds_never_uses_unmatured_target():
    predictions = _predict_folds(
        _panels(),
        folds=(2,),
        lookback=90,
        logistic_c=0.02,
        retrain_every=7,
        seed=7,
    )

    assert predictions
    assert all(
        row["trained_through"] < row["observed_at"]
        for row in predictions
    )


def test_market_wave_benchmark_freezes_validation_choice():
    payload = run_market_wave_benchmark(
        _panels(),
        lookbacks=(60, 90),
        retrain_every=7,
        seed=7,
    )

    assert payload["selected"]["engine"] in {"direct", "wavefield", "hybrid"}
    assert payload["selected"]["lookback"] in {60, 90}
    assert payload["final_test"]["market_panels"] == 3 * 52
    assert payload["oracle_market_factor_ceiling"]["asset_accuracy"] == 1.0
    assert payload["admitted_70"] is True


def test_summary_and_admission_require_stable_assets_and_folds():
    predictions = []
    for fold in (2, 3, 4):
        for index in range(40):
            up = index % 2 == 0
            predictions.append(
                {
                    "fold_index": fold,
                    "market_up": up,
                    "asset_outcomes": [
                        ("BTCUSDT", up),
                        ("ETHUSDT", up),
                    ],
                    "probabilities": {"direct": 0.9 if up else 0.1},
                }
            )
    summary = summarize_predictions(predictions, engine="direct")

    assert summary["market_accuracy"] == 1.0
    assert summary["asset_accuracy"] == 1.0
    assert _admitted_70(summary) is True

    predictions[-1]["asset_outcomes"] = [
        ("BTCUSDT", predictions[-1]["market_up"]),
        ("ETHUSDT", not predictions[-1]["market_up"]),
    ]
    oracle = summarize_oracle(predictions)
    assert 0.0 < oracle["asset_accuracy"] < 1.0
