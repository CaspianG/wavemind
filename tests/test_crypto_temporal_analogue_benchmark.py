from __future__ import annotations

from benchmarks.crypto_market_wave_benchmark import MarketPanel
from benchmarks.crypto_temporal_analogue_benchmark import (
    AnalogueConfig,
    _dtw_distance,
    _predict_folds,
    _sequence_at,
    load_panel_cache,
    run_temporal_analogue_benchmark,
    save_panel_cache,
)


def _panels(*, per_fold: int = 52) -> list[MarketPanel]:
    panels = []
    day = 24 * 60 * 60
    pattern = (False, False, True, True, True, False)
    for fold in range(5):
        for index in range(per_fold):
            global_index = fold * per_fold + index
            up = pattern[global_index % len(pattern)]
            signal = 1.0 if up else -1.0
            panels.append(
                MarketPanel(
                    observed_at=global_index * day,
                    target_at=(global_index + 1) * day,
                    fold_index=fold,
                    features=(
                        signal,
                        float(global_index % len(pattern)),
                        signal * 0.5,
                    ),
                    market_up=up,
                    asset_outcomes=(
                        ("BTCUSDT", up),
                        ("ETHUSDT", up),
                        ("SOLUSDT", up),
                    ),
                )
            )
    return panels


def test_panel_cache_round_trip(tmp_path):
    path = tmp_path / "panels.json.gz"
    panels = _panels(per_fold=10)
    audit = {"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}

    save_panel_cache(path, panels, audit)
    restored, restored_audit = load_panel_cache(path)

    assert restored == panels
    assert restored_audit == audit


def test_dtw_distance_is_zero_for_identical_sequence():
    sequence = [[0.0, 1.0], [1.0, 2.0], [0.5, 3.0]]

    assert _dtw_distance(sequence, sequence, band=1) == 0.0


def test_sequence_restarts_after_gap_without_using_future_state():
    panels = _panels(per_fold=2)[:3]
    day = 24 * 60 * 60
    panels[2] = MarketPanel(
        observed_at=panels[1].observed_at + 4 * day,
        target_at=panels[1].target_at + 4 * day,
        fold_index=panels[2].fold_index,
        features=panels[2].features,
        market_up=panels[2].market_up,
        asset_outcomes=panels[2].asset_outcomes,
    )
    transformed = [[1.0], [2.0], [9.0]]

    sequence = _sequence_at(transformed, panels, 2, length=3)

    assert sequence.tolist() == [[9.0], [9.0], [9.0]]


def test_temporal_predictions_use_only_mature_labels():
    predictions = _predict_folds(
        _panels(),
        folds=(2,),
        config=AnalogueConfig(
            sequence_length=3,
            neighbors=7,
            memory_lookback=90,
        ),
        retrain_every=7,
        seed=7,
    )

    assert predictions
    assert all(
        row["trained_through"] < row["observed_at"]
        for row in predictions
    )


def test_validation_choice_is_frozen_before_final_folds():
    payload = run_temporal_analogue_benchmark(
        _panels(),
        sequence_lengths=(3,),
        neighbor_counts=(7, 11),
        memory_lookback=90,
        retrain_every=7,
        seed=7,
    )

    assert payload["selected"]["engine"] in {
        "knn",
        "dtw",
        "wavefield",
        "hybrid",
    }
    assert payload["selected"]["sequence_length"] == 3
    assert payload["selected"]["neighbors"] in {7, 11}
    assert payload["final_test"]["market_panels"] == 3 * 52
    assert payload["prediction_audit"][
        "all_training_targets_strictly_past"
    ]
