from __future__ import annotations


def test_fusion_comparison_runs_all_variants_on_equal_events(monkeypatch) -> None:
    from benchmarks import crypto_evidence_fusion_benchmark as module
    from benchmarks.crypto_derivatives_field_benchmark import FeatureRow

    calls = []

    def fake_run(rows, *, feature_names, **kwargs):
        del kwargs
        calls.append(tuple(feature_names))
        events = []
        for engine in module.COMPARE_ENGINES:
            for fold in range(5):
                for symbol in ("BTCUSDT", "ETHUSDT"):
                    events.append(
                        {
                            "engine": engine,
                            "fold_index": fold,
                            "symbol": symbol,
                            "timestamp": fold * 100 + (0 if symbol == "BTCUSDT" else 1),
                            "data_end_utc": f"2026-0{fold + 1}-01T00:00:00+00:00",
                            "target_end_utc": f"2026-0{fold + 1}-02T00:00:00+00:00",
                            "direction_hit": 1.0,
                        }
                    )
        summaries = [
            {
                "engine": engine,
                "accuracy": 0.6,
                "selected_signals": 10,
                "worst_symbol_accuracy": 0.6,
            }
            for engine in module.COMPARE_ENGINES
        ]
        return {
            "events": events,
            "summaries": summaries,
            "final_holdout_2026_h1": summaries,
            "admitted_70": [],
            "methodology": {"feature_count": len(feature_names)},
        }

    monkeypatch.setattr(module, "run_multiyear_benchmark", fake_run)
    rows = [
        FeatureRow("BTCUSDT", 1, 2, 0, {}, 1.0),
        FeatureRow("ETHUSDT", 1, 2, 0, {}, -1.0),
    ]

    payload = module.run_evidence_fusion_comparison(
        rows,
        horizon_seconds=86_400,
        base_feature_names=("base",),
    )

    assert len(calls) == 7
    assert list(payload["results"]) == list(module.VARIANT_ORDER)
    assert payload["full_coverage_comparison"][0]["all_signals"] == 10
    assert payload["fusion_admitted_70"] == []
