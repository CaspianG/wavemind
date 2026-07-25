from __future__ import annotations


def test_options_benchmark_compares_identical_coverage(monkeypatch):
    import benchmarks.crypto_options_benchmark as module
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    rows = [
        FeatureRow(
            symbol="BTCUSDT",
            timestamp=index,
            target_timestamp=index + 1,
            fold_index=4,
            features={"base": float(index), "options_atm_iv": 50.0},
            future_return_bps=1.0,
        )
        for index in range(4)
    ]

    def fake_run(*args, feature_names, **kwargs):
        treatment = "options_atm_iv" in feature_names
        events = []
        summaries = []
        for engine in module.COMPARE_ENGINES:
            events.extend(
                {
                    "engine": engine,
                    "symbol": row.symbol,
                    "timestamp": row.timestamp,
                    "target_timestamp": row.target_timestamp,
                    "data_end_utc": f"2026-01-01T00:00:0{row.timestamp}+00:00",
                    "target_end_utc": f"2026-01-01T00:00:0{row.target_timestamp}+00:00",
                    "fold_index": row.fold_index,
                    "direction_hit": 1.0 if treatment else 0.0,
                }
                for row in rows
            )
            summaries.append(
                {
                    "engine": engine,
                    "accuracy": 1.0 if treatment else 0.0,
                    "worst_symbol_accuracy": 1.0 if treatment else 0.0,
                    "selected_signals": len(rows),
                }
            )
        return {
            "events": events,
            "summaries": summaries,
            "final_holdout_2026_h1": summaries,
            "admitted_70": ["fixture"] if treatment else [],
        }

    monkeypatch.setattr(module, "run_multiyear_benchmark", fake_run)

    result = module.run_options_comparison(
        rows,
        horizon_seconds=1,
        base_feature_names=("base",),
    )

    assert result["full_coverage_comparison"][0]["all_signals"] == 4
    assert result["full_coverage_comparison"][0]["delta_final"] == 1.0
    assert result["admitted_70"] == ["fixture"]


def test_options_report_discloses_sampled_tape():
    from benchmarks.crypto_options_benchmark import render_markdown

    payload = {
        "methodology": {
            "protocol": "fixture",
            "rows": 10,
            "assets": ["BTCUSDT"],
        },
        "admitted_70": [],
        "full_coverage_comparison": [
            {
                "engine": "WaveField outcome direction",
                "all_signals": 10,
                "control_all": 0.5,
                "control_final": 0.5,
                "options_all": 0.6,
                "options_final": 0.6,
                "delta_all": 0.1,
                "delta_final": 0.1,
                "options_worst_final_asset": 0.6,
            }
        ],
        "policy_comparison": [
            {
                "engine": "WaveField outcome direction",
                "control_all": 0.5,
                "control_final": 0.5,
                "options_all": 0.6,
                "options_final": 0.6,
                "options_final_signals": 6,
            }
        ],
    }

    report = render_markdown(payload)

    assert "deterministic sample" in report
    assert "admitted at 70%: none" in report
