import json
import subprocess
import sys
from pathlib import Path


def test_leaderboard_status_renderer_writes_public_contract(tmp_path):
    output = tmp_path / "leaderboard-status.json"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/render_leaderboard_status.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema"] == "wavemind.leaderboard_status.v1"
    assert payload["public_url"] == "https://caspiang.github.io/wavemind/"
    assert payload["publishing_status"] == "publishable_with_claim_limits"
    assert payload["publication_contract"]["schema"] == "wavemind.leaderboard_publication.v1"
    assert payload["publication_contract"]["status"] == "pass"
    assert payload["publication_contract"]["workflow"] == (
        ".github/workflows/benchmark-leaderboard.yml"
    )
    assert payload["publication_contract"]["schedule_cron"] == "17 4 * * 1"
    assert payload["publication_contract"]["expected_scheduled_refresh_profile"] == "weekly-fast"
    assert payload["publication_contract"]["github_pages"]["status_json"] == (
        "data/leaderboard-status.json"
    )
    assert payload["publication_contract"]["checks"] == {
        "weekly_schedule": True,
        "manual_dispatch": True,
        "github_pages_upload": True,
        "github_pages_deploy": True,
        "review_artifact_uploaded": True,
        "no_scheduled_bot_commit_to_main": True,
        "strict_freshness_gate": True,
        "machine_status_published": True,
    }
    assert "do not commit generated benchmark artifacts back to main" in (
        payload["publication_contract"]["review_policy"]
    )
    assert "100M production claims stay locked" in (
        payload["publication_contract"]["claim_policy"]
    )
    assert payload["freshness_gate"]["schema"] == "wavemind.leaderboard_freshness.v1"
    assert payload["freshness_gate"]["status"] == "pass"
    assert payload["freshness_gate"]["source_count"] == len(payload["source_files"])
    assert payload["freshness_gate"]["fresh_count"] == payload["freshness_gate"]["source_count"]
    assert payload["freshness_gate"]["stale_count"] == 0
    assert payload["freshness_gate"]["missing_count"] == 0
    assert payload["freshness_gate"]["no_timestamp_count"] == 0
    assert payload["freshness_gate"]["load_error_count"] == 0
    assert payload["freshness_gate"]["stale_sources"] == []
    assert payload["freshness_gate"]["missing_sources"] == []
    assert payload["freshness_gate"]["no_timestamp_sources"] == []
    assert {
        "benchmarks/production_scale_run_plan.json",
        "benchmarks/agent_coherence_results.json",
        "benchmarks/agent_impact_results.json",
        "benchmarks/structured_memory_results.json",
        "benchmarks/multimodal_admission_results.json",
        "benchmarks/memory_os_intelligence_results.json",
        "benchmarks/memory_os_policy_evolution_results.json",
        "benchmarks/cluster_autoscale_results.json",
        "benchmarks/kubernetes_operator_smoke_results.json",
        "benchmarks/kubernetes_cluster_network_smoke_results.json",
        "benchmarks/scale_readiness_results.json",
        "benchmarks/cost_efficiency_results.json",
    }.issubset({row["path"] for row in payload["freshness_gate"]["sources"]})
    assert payload["benchmark_matrix"]["schema"] == "wavemind.benchmark_matrix.v1"
    assert payload["benchmark_matrix"]["implemented_count"] >= 20
    assert payload["benchmark_matrix"]["runner_ready_count"] >= 1
    assert payload["benchmark_matrix"]["planned_count"] >= 1
    assert payload["artifact_audit"]["status"] == "pass"
    assert payload["production_readiness"]["overall_status"] == "pass"
    assert payload["production_readiness"]["readiness_score"] == 1.0
    assert payload["agent_quality"]["schema"] == "wavemind.agent_coherence_benchmark.v1"
    assert payload["agent_quality"]["status"] == "pass"
    assert payload["agent_quality"]["wavemind_task_success_rate"] > (
        payload["agent_quality"]["best_baseline_task_success_rate"]
    )
    assert payload["agent_quality"]["task_success_lift"] > 0.0
    assert payload["agent_quality"]["wavemind_context_budget_saved"] > 0.9
    assert payload["agent_quality"]["wavemind_stale_error_rate"] <= 0.05
    assert "Chroma static" in payload["agent_quality"]["baseline_engines"]
    assert "WaveMind + Memory OS" not in payload["agent_quality"]["baseline_engines"]
    assert "WaveMind + Memory OS" in payload["agent_quality"]["wavemind_variant_engines"]
    assert payload["agent_quality"]["memory_os_worker_ok"] is True
    assert payload["agent_quality"]["memory_os_prewarm_warmed"] >= 1
    assert payload["agent_quality"]["memory_os_predictive_prefetch_warmed"] >= 1
    assert payload["agent_quality"]["memory_os_priority_predictions"] >= 1
    assert payload["agent_quality"]["memory_os_cache_hit_rate"] > 0
    assert payload["agent_impact"]["schema"] == "wavemind.agent_impact_leaderboard.v1"
    assert payload["agent_impact"]["status"] == "pass"
    assert payload["agent_impact"]["benchmark_count"] >= 6
    assert payload["agent_impact"]["wavemind_row_count"] >= 6
    assert payload["agent_impact"]["baseline_row_count"] >= 6
    assert payload["agent_impact"]["wavemind_primary_wins"] == (
        payload["agent_impact"]["benchmark_count"]
    )
    assert payload["agent_impact"]["average_primary_lift"] > 0
    assert payload["agent_impact"]["average_context_saved"] > 0.5
    assert payload["agent_impact"]["average_stale_safety_score"] >= 0.95
    assert "agent success outside the listed scenarios" in (
        payload["agent_impact"]["claim_boundary"]
    )
    assert "benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json" in (
        payload["agent_impact"]["source_files"]
    )
    assert payload["structured_memory"]["schema"] == "wavemind.structured_memory_report.v1"
    assert payload["structured_memory"]["status"] == "pass"
    assert payload["structured_memory"]["modality_count"] == 7
    assert payload["structured_memory"]["passed_check_count"] == (
        payload["structured_memory"]["check_count"]
    )
    assert payload["structured_memory"]["precision_at_1"] == 1.0
    assert payload["structured_memory"]["cross_modal_precision_at_1"] == 1.0
    assert payload["structured_memory"]["cross_modal_vectors_persisted_rate"] == 1.0
    assert payload["structured_memory"]["cross_modal_provenance_rate"] == 1.0
    assert payload["structured_memory"]["precomputed_vector_precision_at_1"] == 1.0
    assert payload["structured_memory"]["encoder_contract_ok"] is True
    assert payload["structured_memory"]["encoder_health_ok"] is True
    assert payload["structured_memory"]["encoder_health_global_precision_at_1"] == 1.0
    assert payload["structured_memory"]["encoder_health_target_modality_routing_rate"] == 1.0
    assert payload["structured_memory"]["encoder_health_dimension_match_rate"] == 1.0
    assert payload["structured_memory"]["encoder_health_query_encode_p95_ms"] <= 50.0
    assert payload["structured_memory"]["temporal_event_precision_at_1"] == 1.0
    assert payload["structured_memory"]["knowledge_graph_precision_at_1"] == 1.0
    assert payload["structured_memory"]["knowledge_graph_path_precision_at_1"] == 1.0
    assert payload["structured_memory"]["asset_manifest_verified"] is True
    assert "production multimodal model quality" in (
        payload["structured_memory"]["claim_boundary"]
    )
    assert payload["memory_os_intelligence"]["schema"] == (
        "wavemind.memory_os_intelligence_report.v1"
    )
    assert payload["memory_os_intelligence"]["status"] == "pass"
    assert payload["memory_os_intelligence"]["passed_check_count"] == (
        payload["memory_os_intelligence"]["check_count"]
    )
    assert payload["memory_os_intelligence"]["worker_ok"] is True
    assert payload["memory_os_intelligence"]["prewarm_warmed"] >= 2
    assert payload["memory_os_intelligence"]["predictive_prefetch_warmed"] >= 6
    assert payload["memory_os_intelligence"]["transition_prefetch_hit"] is True
    assert payload["memory_os_intelligence"]["priority_predictions"] >= 2
    assert payload["memory_os_intelligence"]["forgetting_demotions"] >= 1
    assert payload["memory_os_intelligence"]["concepts_created"] >= 1
    assert payload["memory_os_intelligence"]["redis_memory_os_cross_worker_hit"] is True
    assert payload["memory_os_intelligence"]["agent_task_success_rate"] >= 0.9
    assert payload["memory_os_intelligence"]["agent_context_budget_saved"] >= 0.9
    assert payload["memory_os_intelligence"]["canary_status"] == "pass"
    assert payload["memory_os_intelligence"]["admission_status"] == "plan_only"
    assert "unattended production Memory OS automation" in (
        payload["memory_os_intelligence"]["claim_boundary"]
    )
    assert payload["cluster_autoscale"]["schema"] == (
        "wavemind.cluster_autoscale_report.v1"
    )
    assert payload["cluster_autoscale"]["status"] == "pass"
    assert payload["cluster_autoscale"]["passed_check_count"] == (
        payload["cluster_autoscale"]["check_count"]
    )
    assert payload["cluster_autoscale"]["simulated_memories"] == 1_000_000
    assert payload["cluster_autoscale"]["namespace_count"] == 4096
    assert payload["cluster_autoscale"]["autoscaler_target_memories"] == 10_000_000
    assert payload["cluster_autoscale"]["autoscaler_required_nodes"] >= 50
    assert payload["cluster_autoscale"]["operator_status_phase"] == "Ready"
    assert payload["cluster_autoscale"]["operator_status_ready"] is True
    assert payload["cluster_autoscale"]["operator_memory_os_ready"] is True
    assert payload["cluster_autoscale"]["control_plane_ok"] is True
    assert payload["cluster_autoscale"]["operator_controller_replicas"] >= 2
    assert payload["cluster_autoscale"]["operator_leader_election"] is True
    assert payload["cluster_autoscale"]["operator_lease_backend"] == "coordination.k8s.io/v1"
    assert payload["cluster_autoscale"]["operator_pdb_rbac"] is True
    assert payload["cluster_autoscale"]["operator_has_pod_disruption_budget"] is True
    assert payload["cluster_autoscale"]["operator_statefulset_rolling_update"] is True
    assert payload["cluster_autoscale"]["operator_statefulset_topology_spread_keys"] == [
        "kubernetes.io/hostname",
        "topology.kubernetes.io/zone",
    ]
    assert payload["kubernetes_operator_failover"]["status"] == "pass"
    assert payload["kubernetes_operator_failover"]["node_count"] == 4
    assert payload["kubernetes_operator_failover"]["operator_node_count"] >= 2
    assert payload["kubernetes_operator_failover"]["lease_transitions_after"] >= 1
    assert payload["kubernetes_operator_failover"]["passed_checks"] == 14
    assert payload["kubernetes_operator_failover"]["api_healthy_after_recovery"] is True
    assert payload["kubernetes_operator_failover"]["topology_spread_constraint_count"] == 2
    assert payload["kubernetes_operator_failover"]["pdb_min_available"] == 3
    assert payload["kubernetes_operator_failover"]["rolling_upgrade_revision_changed"] is True
    assert payload["kubernetes_operator_failover"]["rolling_upgrade_replaced_pods"] == 4
    assert payload["kubernetes_operator_failover"]["api_healthy_after_upgrade"] is True
    assert "does not unlock remote production" in (
        payload["kubernetes_operator_failover"]["claim_boundary"]
    )
    assert (
        payload["cluster_autoscale"]["distributed_http_recalled_after_primary_loss"]
        is True
    )
    assert payload["cluster_autoscale"]["active_active_convergence_rate"] == 1.0
    assert payload["cluster_autoscale"]["http_active_active_success_rate"] == 1.0
    assert payload["cluster_autoscale"]["field_crdt_commutative_convergence"] is True
    assert payload["cluster_autoscale"]["capacity_target_memories"] == 100_000_000
    assert payload["cluster_autoscale"]["capacity_node_count"] >= 128
    assert payload["cluster_autoscale"]["capacity_zones"] >= 8
    assert payload["cluster_autoscale"]["capacity_valid_plan"] is True
    assert "not a real 100M vector-query latency benchmark" in (
        payload["cluster_autoscale"]["claim_boundary"]
    )
    assert payload["memory_os_policy"]["schema"] == "wavemind.scale_readiness_benchmark.v1"
    assert payload["memory_os_policy"]["status"] == "pass"
    assert payload["memory_os_policy"]["policy_status"] == "architecture_required"
    assert payload["memory_os_policy"]["decision_count"] >= 6
    assert payload["memory_os_policy"]["required_decisions_present"] is True
    assert {
        "prefetch-policy",
        "priority-policy",
        "forgetting-policy",
        "consolidation-policy",
        "scale-policy",
        "coordination-policy",
    }.issubset(set(payload["memory_os_policy"]["decision_ids"]))
    assert payload["memory_os_policy"]["scale_strategy"] == (
        "external-index-sharding-and-production-controls"
    )
    assert payload["memory_os_policy"]["history_trend"] == "first_run"
    assert payload["memory_os_policy"]["history_previous_runs"] == 0
    assert payload["memory_os_policy"]["repeated_required_ids"] == []
    assert payload["memory_os_policy"]["history_escalations"] == 0
    assert payload["memory_os_policy_evolution"]["schema"] == (
        "wavemind.memory_os_policy_evolution.v1"
    )
    assert payload["memory_os_policy_evolution"]["status"] == "pass"
    assert payload["memory_os_policy_evolution"]["ok"] is True
    assert payload["memory_os_policy_evolution"]["cycles"] >= 3
    assert payload["memory_os_policy_evolution"]["passed_check_count"] == (
        payload["memory_os_policy_evolution"]["check_count"]
    )
    assert payload["memory_os_policy_evolution"]["decision_coverage_rate"] == 1.0
    assert payload["memory_os_policy_evolution"]["repeated_required_cycle_count"] >= 2
    assert payload["memory_os_policy_evolution"]["history_suggestion_count"] >= 1
    assert payload["memory_os_policy_evolution"]["escalation_action_count"] >= 1
    assert "scale-policy" in (
        payload["memory_os_policy_evolution"]["scheduler_policy_escalation_ids"]
    )
    assert payload["memory_os_policy_evolution"]["prewarm_warmed"] >= 1
    assert payload["memory_os_policy_evolution"]["predictive_prefetch_warmed"] >= 1
    assert payload["memory_os_policy_evolution"]["priority_predictions"] >= 1
    assert "unattended production automation" in (
        payload["memory_os_policy_evolution"]["claim_boundary"]
    )
    assert payload["memory_os_policy_bundle"]["schema"] == (
        "wavemind.memory_os_policy_bundle.v1"
    )
    assert payload["memory_os_policy_bundle"]["status"] == "staging_ready"
    assert payload["memory_os_policy_bundle"]["ok"] is True
    assert payload["memory_os_policy_bundle"]["summary"]["staging_promotable"] is True
    assert payload["memory_os_policy_bundle"]["summary"]["production_promotable"] is False
    assert payload["memory_os_policy_bundle"]["summary"]["production_locked"] is True
    assert payload["memory_os_policy_bundle"]["runtime_policy"]["production_auto_enable"] is False
    assert payload["memory_os_policy_bundle"]["kubernetes_patch"]["spec"]["productionAutoEnable"] is False
    assert payload["strict_production_evidence"]["overall_status"] == "action_required"
    assert payload["strict_production_evidence"]["summary"]["total_requirements"] == 8
    assert payload["strict_production_evidence"]["action_required"]
    assert payload["production_evidence_bundle"]["schema"] == (
        "wavemind.production_evidence_bundle.v1"
    )
    assert payload["production_evidence_bundle"]["claim_status"] == "claims_limited"
    assert payload["production_evidence_bundle"]["next_action_count"] == 8
    assert payload["production_evidence_bundle"]["production_scale_run_contract"]["status"] == "available"
    assert payload["production_evidence_env"]["schema"] == (
        "wavemind.production_evidence_env_contract.v1"
    )
    assert payload["production_evidence_env"]["overall_status"] in {
        "action_required",
        "ready",
    }
    assert payload["production_evidence_env"]["summary"]["required_env_count"] >= 9
    assert payload["production_evidence_env"]["github_secret_count"] >= 9
    assert payload["production_evidence_env"]["check_count"] == 6
    assert payload["production_evidence_dispatch"]["schema"] == (
        "wavemind.production_evidence_dispatch.v1"
    )
    assert payload["production_evidence_dispatch"]["overall_status"] in {
        "action_required",
        "ready_to_dispatch",
        "complete",
    }
    assert payload["production_evidence_dispatch"]["summary"]["total_jobs"] == 8
    assert any(
        row["id"] == "hundred_million_remote_load"
        for row in payload["production_evidence_dispatch"]["jobs"]
    )
    assert payload["release_claims"]["schema"] == "wavemind.release_claims.v1"
    assert payload["release_claims"]["release_status"] == "core_release_ready"
    assert payload["release_claims"]["claim_status"] == "claims_limited"
    assert payload["release_claims"]["summary"]["allowed_claim_count"] >= 1
    assert payload["release_claims"]["summary"]["locked_claim_count"] >= 1
    assert any(
        row["claim"] == "10M-100M service-backed production scale"
        for row in payload["release_claims"]["locked_claims"]
    )
    assert payload["scale_gap"]["schema"] == "wavemind.scale_gap.v1"
    assert payload["scale_gap"]["overall_status"] == "action_required"
    assert payload["scale_gap"]["summary"]["total_profiles"] == 5
    assert payload["scale_gap"]["summary"]["planned_target_memories"] == 180_000_000
    assert any(
        row["profile"] == "qdrant-sharded-100m"
        for row in payload["scale_gap"]["profile_gaps"]
    )
    assert payload["strict_evidence_readiness"]["schema"] == (
        "wavemind.strict_evidence_readiness.v1"
    )
    assert payload["strict_evidence_readiness"]["status"] == "pass"
    assert payload["strict_evidence_readiness"]["readiness_status"] == (
        "action_required"
    )
    assert payload["strict_evidence_readiness"]["claim_status"] == "claims_limited"
    assert payload["strict_evidence_readiness"]["summary"]["total_requirements"] == 8
    assert payload["strict_evidence_readiness"]["summary"]["target_memories_total"] == (
        180_000_000
    )
    assert payload["strict_evidence_readiness"]["summary"]["can_auto_run_now_count"] == 0
    assert payload["strict_evidence_readiness"]["summary"]["check_counts"] == {"pass": 8}
    assert any(
        row["id"] == "hundred_million_remote_load"
        and row["target_memories"] == 100_000_000
        and row["locked_claim"] == "10M-100M service-backed production scale"
        for row in payload["strict_evidence_readiness"]["requirements"]
    )
    assert "Readiness report only" in payload["strict_evidence_readiness"][
        "claim_boundary"
    ]
    assert payload["cluster_admission"]["schema"] == (
        "wavemind.cluster_admission.v1"
    )
    assert payload["cluster_admission"]["status"] in {
        "admitted",
        "plan_only",
        "blocked",
    }
    assert payload["cluster_admission"]["admitted"] is False
    assert payload["cluster_admission"]["claim_boundary"] == (
        "external_http_cluster_evidence_required"
    )
    assert payload["cluster_admission"]["summary"]["strict_status"] == (
        "action_required"
    )
    assert payload["cluster_admission"]["required_evidence"]["id"] == (
        "external_http_cluster"
    )
    assert payload["cluster_admission"]["requested_evidence"]["status"] == "fail"
    assert payload["active_active_admission"]["schema"] == (
        "wavemind.active_active_admission.v1"
    )
    assert payload["active_active_admission"]["status"] in {
        "admitted",
        "plan_only",
        "blocked",
    }
    assert payload["active_active_admission"]["admitted"] is False
    assert payload["active_active_admission"]["claim_boundary"] == (
        "external_active_active_evidence_required"
    )
    assert payload["active_active_admission"]["summary"]["strict_status"] == (
        "action_required"
    )
    assert payload["active_active_admission"]["required_evidence"]["id"] == (
        "external_http_active_active"
    )
    assert payload["serverless_admission"]["schema"] == (
        "wavemind.serverless_admission.v1"
    )
    assert payload["serverless_admission"]["status"] in {
        "admitted",
        "plan_only",
        "blocked",
    }
    assert payload["serverless_admission"]["admitted"] is False
    assert payload["serverless_admission"]["claim_boundary"] == (
        "remote_serverless_telemetry_required"
    )
    assert payload["serverless_admission"]["summary"]["strict_status"] == (
        "action_required"
    )
    assert payload["serverless_admission"]["required_evidence"]["id"] == (
        "serverless_remote_telemetry"
    )
    assert payload["memory_os_admission"]["schema"] == "wavemind.memory_os_admission.v1"
    assert payload["memory_os_admission"]["status"] in {"admitted", "plan_only", "blocked"}
    assert payload["memory_os_admission"]["summary"]["requirement_count"] >= 10
    assert "hot-query-signal" in {
        row["id"] for row in payload["memory_os_admission"]["requirements"]
    }
    assert payload["multimodal_admission"]["schema"] == (
        "wavemind.multimodal_admission.v1"
    )
    assert payload["multimodal_admission"]["status"] in {
        "admitted",
        "plan_only",
        "blocked",
    }
    assert payload["multimodal_admission"]["admitted"] is False
    assert payload["multimodal_admission"]["claim_boundary"] == (
        "external_multimodal_encoder_evidence_required"
    )
    assert payload["multimodal_admission"]["summary"]["structured_status"] == "pass"
    assert payload["multimodal_admission"]["required_evidence"]["id"] == (
        "external_multimodal_encoder"
    )
    assert payload["multimodal_admission"]["requested_evidence"]["status"] == (
        "action_required"
    )
    assert payload["production_scale_run_plan"]["schema"] == "wavemind.production_scale_run_plan.v1"
    assert payload["production_scale_run_plan"]["total_profiles"] == 5
    assert payload["production_scale_run_plan"]["target_memories_total"] == 180_000_000
    assert payload["production_scale_run_plan"]["monthly_budget_usd_total"] >= 20_000.0
    assert payload["production_scale_run_plan"]["cost_status_counts"]["valid_slo"] == 5
    assert "faiss-ivfpq-50m" in payload["production_scale_run_plan"]["pareto_frontier_profiles"]
    assert (
        payload["production_scale_run_plan"]["best_by_target_class"]["50m"]
        == "faiss-ivfpq-50m"
    )
    assert "qdrant-sharded-100m" in payload["production_scale_run_plan"]["profiles"]
    assert payload["cost_efficiency"]["schema"] == "wavemind.cost_efficiency_leaderboard.v1"
    assert payload["cost_efficiency"]["measured_row_count"] >= 10
    assert payload["cost_efficiency"]["planned_row_count"] == 5
    assert payload["cost_efficiency"]["measured_slo_pass_count"] >= 1
    assert payload["cost_efficiency"]["measured_valid_cost_count"] >= 1
    assert payload["cost_efficiency"]["planned_valid_cost_count"] == 5
    assert "1m" in payload["cost_efficiency"]["best_measured_by_target_class"]
    assert payload["cost_efficiency"]["best_planned_by_target_class"]["50m"] == (
        "faiss-ivfpq-50m"
    )
    assert "qdrant-sharded-100m" in payload["cost_efficiency"]["planned_frontier_profiles"]
    assert "Planned rows are capacity and cost contracts only" in (
        payload["cost_efficiency"]["claim_boundary"]
    )
    assert {
        "external_http_active_active",
        "qdrant_sharded_10m_service",
        "hundred_million_remote_load",
    }.issubset(
        {entry["id"] for entry in payload["strict_production_evidence"]["action_required"]}
    )
    assert "benchmarks/benchmark_matrix_results.json" in payload["source_files"]
    assert "benchmarks/production_evidence_results.json" in payload["source_files"]
    assert "benchmarks/production_evidence_env_contract.json" in payload["source_files"]
    assert "benchmarks/production_evidence_bundle_results.json" in payload["source_files"]
    assert "benchmarks/production_evidence_dispatch_results.json" in payload["source_files"]
    assert "benchmarks/release_claims_results.json" in payload["source_files"]
    assert "benchmarks/scale_gap_results.json" in payload["source_files"]
    assert "benchmarks/strict_evidence_readiness_results.json" in payload["source_files"]
    assert "benchmarks/cluster_admission_results.json" in payload["source_files"]
    assert "benchmarks/active_active_admission_results.json" in payload["source_files"]
    assert "benchmarks/serverless_admission_results.json" in payload["source_files"]
    assert "benchmarks/cost_efficiency_results.json" in payload["source_files"]
    assert "benchmarks/agent_impact_results.json" in payload["source_files"]
    assert "benchmarks/structured_memory_results.json" in payload["source_files"]
    assert "benchmarks/multimodal_admission_results.json" in payload["source_files"]
    assert "benchmarks/memory_os_intelligence_results.json" in payload["source_files"]
    assert "benchmarks/memory_os_policy_evolution_results.json" in payload["source_files"]
    assert "benchmarks/memory_os_policy_bundle_results.json" in payload["source_files"]
    assert "benchmarks/cluster_autoscale_results.json" in payload["source_files"]
    assert "benchmarks/kubernetes_operator_smoke_results.json" in payload["source_files"]
    assert "benchmarks/kubernetes_cluster_network_smoke_results.json" in payload["source_files"]
    assert "benchmarks/memory_os_admission_results.json" in payload["source_files"]
    assert "benchmarks/production_scale_run_plan.json" in payload["source_files"]
    assert "benchmarks/agent_coherence_results.json" in payload["source_files"]
    assert "benchmarks/scale_readiness_results.json" in payload["source_files"]
    assert payload["load_errors"] == []


def test_checked_in_leaderboard_status_is_present_and_machine_readable():
    payload = json.loads(
        Path("docs/data/leaderboard-status.json").read_text(encoding="utf-8")
    )

    assert payload["schema"] == "wavemind.leaderboard_status.v1"
    assert payload["publishing_status"] in {
        "publishable",
        "publishable_with_claim_limits",
    }
    assert payload["freshness_gate"]["status"] == "pass"
    assert payload["freshness_gate"]["no_timestamp_count"] == 0
    assert payload["freshness_gate"]["missing_count"] == 0
    assert payload["freshness_gate"]["stale_count"] == 0
    assert payload["artifact_audit"]["status"] == "pass"
    assert payload["production_readiness"]["overall_status"] == "pass"
    assert payload["agent_quality"]["status"] == "pass"
    assert payload["agent_impact"]["status"] == "pass"
    assert payload["structured_memory"]["status"] == "pass"
    assert payload["memory_os_intelligence"]["status"] == "pass"
    assert payload["memory_os_policy_evolution"]["status"] == "pass"
    assert payload["memory_os_policy_bundle"]["status"] == "staging_ready"
    assert payload["cluster_autoscale"]["status"] == "pass"
    assert payload["kubernetes_operator_failover"]["status"] == "pass"
    assert payload["memory_os_policy"]["status"] == "pass"
    assert payload["production_evidence_bundle"]["claim_status"] in {
        "claims_limited",
        "claims_unlocked",
    }
    assert payload["production_evidence_env"]["schema"] == (
        "wavemind.production_evidence_env_contract.v1"
    )
    assert payload["production_evidence_env"]["summary"]["required_env_count"] >= 9
    assert payload["production_evidence_dispatch"]["schema"] == (
        "wavemind.production_evidence_dispatch.v1"
    )
    assert payload["production_evidence_dispatch"]["summary"]["total_jobs"] == 8
    assert payload["release_claims"]["release_status"] in {
        "core_release_ready",
        "full_production_claims_ready",
    }
    assert payload["scale_gap"]["schema"] == "wavemind.scale_gap.v1"
    assert payload["strict_evidence_readiness"]["schema"] == (
        "wavemind.strict_evidence_readiness.v1"
    )
    assert payload["strict_evidence_readiness"]["status"] == "pass"
    assert payload["active_active_admission"]["schema"] == (
        "wavemind.active_active_admission.v1"
    )
    assert payload["serverless_admission"]["schema"] == (
        "wavemind.serverless_admission.v1"
    )
    assert payload["cost_efficiency"]["schema"] == "wavemind.cost_efficiency_leaderboard.v1"
    assert payload["memory_os_admission"]["schema"] == "wavemind.memory_os_admission.v1"
    assert payload["multimodal_admission"]["schema"] == (
        "wavemind.multimodal_admission.v1"
    )
    assert payload["production_scale_run_plan"]["schema"] == "wavemind.production_scale_run_plan.v1"
    assert payload["memory_os_intelligence"]["schema"] == (
        "wavemind.memory_os_intelligence_report.v1"
    )
    assert payload["memory_os_policy_evolution"]["schema"] == (
        "wavemind.memory_os_policy_evolution.v1"
    )
    assert payload["memory_os_policy_bundle"]["schema"] == (
        "wavemind.memory_os_policy_bundle.v1"
    )
    assert payload["cluster_autoscale"]["schema"] == (
        "wavemind.cluster_autoscale_report.v1"
    )
