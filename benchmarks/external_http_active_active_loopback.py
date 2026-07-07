from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks import local_http_active_active_smoke as active_runner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Start real localhost WaveMind API region processes, then run the "
            "external URL-based active-active benchmark against their region "
            "URLs. This proves the external transport contract without claiming "
            "remote Kubernetes/serverless evidence."
        )
    )
    parser.add_argument("--regions", type=int, default=3)
    parser.add_argument("--replicas-per-region", type=int, default=3)
    parser.add_argument("--namespace-prefix", default=None)
    parser.add_argument("--namespace-count", type=int, default=16)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--readiness-timeout", type=float, default=25.0)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--deployment-id", default=None)
    parser.add_argument("--environment", default="local-loopback")
    parser.add_argument("--source", default="loopback-api-regions")
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--min-convergence-rate", type=float, default=1.0)
    parser.add_argument("--min-delete-suppression-rate", type=float, default=1.0)
    parser.add_argument("--p99-slo-ms", type=float, default=1500.0)
    parser.add_argument("--fail-on-slo", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/external_http_active_active_loopback_results.json"),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.regions < 2:
        raise ValueError("--regions must be at least 2")
    if args.replicas_per_region < 1:
        raise ValueError("--replicas-per-region must be positive")
    if args.namespace_count <= 0:
        raise ValueError("--namespace-count must be positive")


def _external_args(
    args: argparse.Namespace,
    regions: list[active_runner.LocalReplicatedRegion],
) -> argparse.Namespace:
    deployment_id = args.deployment_id or f"loopback-active-active-{int(time.time())}"
    namespace_prefix = args.namespace_prefix or f"tenant:external-active-active-loopback:{deployment_id}"
    return argparse.Namespace(
        region=[f"{region.id}={region.address}" for region in regions],
        regions_file=None,
        regions=args.regions,
        replicas_per_region=args.replicas_per_region,
        namespace_prefix=namespace_prefix,
        namespace_count=args.namespace_count,
        limit=args.limit,
        timeout=args.timeout,
        readiness_timeout=args.readiness_timeout,
        api_key=args.api_key,
        deployment_id=deployment_id,
        environment=args.environment,
        source=args.source,
        min_success_rate=args.min_success_rate,
        min_convergence_rate=args.min_convergence_rate,
        min_delete_suppression_rate=args.min_delete_suppression_rate,
        p99_slo_ms=args.p99_slo_ms,
        fail_on_slo=args.fail_on_slo,
        output=args.output,
    )


def run_from_args(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    started_at = time.time()
    regions: list[active_runner.LocalReplicatedRegion] = []

    with tempfile.TemporaryDirectory(prefix="wavemind-active-active-loopback-") as directory:
        root = Path(directory)
        try:
            for index in range(args.regions):
                regions.append(
                    active_runner.start_replicated_region(
                        root,
                        f"region-{index:03d}",
                        replicas_per_region=args.replicas_per_region,
                        readiness_timeout_seconds=args.readiness_timeout,
                        capture_output=False,
                    )
                )
            payload = active_runner.run_from_args(_external_args(args, regions))
            scenario = payload["scenario"]
            scenario["started_api_processes"] = len(regions)
            scenario["loopback_duration_ms"] = (time.time() - started_at) * 1000.0
            scenario["description"] = (
                "External URL-based active-active runner executed against real "
                "localhost WaveMind API region processes. This proves the "
                "region transport, namespace-delta sync, cursor idempotency, "
                "delete propagation, and SLO contract without claiming remote "
                "Kubernetes/serverless evidence."
            )
            return payload
        finally:
            active_runner.stop_regions(regions)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = run_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = payload["results"][0]
    print("| profile | key metric | value |")
    print("|---|---|---:|")
    print(f"| external loopback active-active | regions | {result['region_count']} |")
    print(f"| external loopback active-active | namespaces | {result['namespaces']} |")
    print(f"| external loopback active-active | convergence_rate | {result['convergence_rate']:.3f} |")
    print(
        "| external loopback active-active | delete_suppression_rate | "
        f"{result['delete_suppression_rate']:.3f} |"
    )
    print(f"| external loopback active-active | success_rate | {result['success_rate']:.3f} |")
    print(f"| external loopback active-active | final_noop_records_imported | {result['final_noop_records_imported']} |")
    print(f"| external loopback active-active | p99_operation_ms | {result['p99_operation_ms']:.2f} |")
    print(f"| external loopback active-active | slo_pass | {result['slo_pass']} |")
    print(f"\nWrote {args.output}")
    if args.fail_on_slo and not result["slo_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
