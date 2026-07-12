from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from wavemind.remote_scale_lab import (
    RemoteScaleLabError,
    attest_remote_qdrant_scale_inventory,
    close_remote_qdrant_tunnels,
    deploy_remote_qdrant_scale_inventory,
    load_remote_scale_inventory,
    open_remote_qdrant_tunnels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attested remote Qdrant 100M scale lab")
    parser.add_argument(
        "action", choices=("plan", "attest", "deploy", "tunnel", "close-tunnels")
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--compose",
        type=Path,
        default=PROJECT_ROOT / "deploy" / "remote-scale" / "docker-compose.yml",
    )
    parser.add_argument("--min-cpu", type=int, default=2)
    parser.add_argument("--min-memory-gb", type=float, default=16.0)
    parser.add_argument("--min-disk-free-gb", type=float)
    parser.add_argument("--local-port-base", type=int, default=16_333)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inventory = load_remote_scale_inventory(args.inventory)
        if args.action == "plan":
            payload = {
                "schema": "wavemind.remote_qdrant_scale_plan.v1",
                "status": "ready",
                "deployment_id": inventory.deployment_id,
                "environment": inventory.environment,
                "source": inventory.source,
                "image": inventory.image,
                "target_vectors": inventory.target_vectors,
                "vector_dim": inventory.vector_dim,
                "shard_count": len(inventory.shards),
                "region_count": len({row.region for row in inventory.shards}),
                "estimated_application_storage_gb": inventory.estimated_application_storage_gb,
                "required_disk_per_shard_gb": inventory.required_disk_per_shard_gb(),
                "required_environment": [
                    "WAVEMIND_REMOTE_SCALE_INVENTORY_JSON",
                    "WAVEMIND_REMOTE_SCALE_SSH_PRIVATE_KEY",
                    "WAVEMIND_REMOTE_SCALE_SSH_KNOWN_HOSTS",
                    "WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY",
                ],
                "claim_boundary": "Validated plan only; no remote capacity or 100M SLO is claimed.",
            }
        elif args.action == "attest":
            payload = attest_remote_qdrant_scale_inventory(
                inventory,
                min_cpu=args.min_cpu,
                min_memory_gb=args.min_memory_gb,
                min_disk_free_gb=args.min_disk_free_gb,
            )
        elif args.action == "deploy":
            attestation = attest_remote_qdrant_scale_inventory(
                inventory,
                min_cpu=args.min_cpu,
                min_memory_gb=args.min_memory_gb,
                min_disk_free_gb=args.min_disk_free_gb,
            )
            if attestation["status"] != "pass":
                raise RemoteScaleLabError("remote scale attestation must pass before deployment")
            payload = deploy_remote_qdrant_scale_inventory(
                inventory,
                compose_text=args.compose.read_text(encoding="utf-8"),
                api_key=os.environ.get("WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY", ""),
            )
        elif args.action == "tunnel":
            payload = open_remote_qdrant_tunnels(
                inventory,
                api_key=os.environ.get("WAVEMIND_REMOTE_SCALE_QDRANT_API_KEY", ""),
                local_port_base=args.local_port_base,
            )
        else:
            payload = close_remote_qdrant_tunnels(inventory)
        _write(args.output, payload)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("status") in {"pass", "ready"} else 1
    except (OSError, ValueError, json.JSONDecodeError, RemoteScaleLabError) as exc:
        print(f"remote-scale-lab: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
