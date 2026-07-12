from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.remote_lab import (
    RemoteLabError,
    attest_remote_inventory,
    deploy_remote_inventory,
    load_remote_inventory,
    probe_public_regions,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Attest and deploy a real three-region WaveMind lab")
    parser.add_argument("action", choices=["plan", "attest", "deploy", "probe"])
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--compose", type=Path, default=PROJECT_ROOT / "deploy/remote/docker-compose.yml")
    parser.add_argument("--min-cpu", type=int, default=2)
    parser.add_argument("--min-memory-gb", type=float, default=2.0)
    parser.add_argument("--min-disk-free-gb", type=float, default=10.0)
    args = parser.parse_args()

    try:
        inventory = load_remote_inventory(args.inventory)
        if args.action == "plan":
            payload = {
                "schema": "wavemind.remote_production_plan.v1",
                "status": "ready",
                "deployment_id": inventory.deployment_id,
                "environment": inventory.environment,
                "image": inventory.image,
                "region_count": len(inventory.regions),
                "regions": [
                    {
                        "id": row.id,
                        "ssh_host": row.ssh_host,
                        "public_url": row.public_url,
                        "region": row.region,
                        "zone": row.zone,
                        "provider": row.provider,
                    }
                    for row in inventory.regions
                ],
                "required_environment": [
                    "WAVEMIND_REMOTE_API_KEY",
                    "WAVEMIND_REMOTE_POSTGRES_PASSWORD",
                ],
                "claim_boundary": "Plan only; no remote execution or production evidence.",
            }
        elif args.action == "attest":
            payload = attest_remote_inventory(
                inventory,
                min_cpu=args.min_cpu,
                min_memory_gb=args.min_memory_gb,
                min_disk_free_gb=args.min_disk_free_gb,
            )
        elif args.action == "deploy":
            attestation = attest_remote_inventory(
                inventory,
                min_cpu=args.min_cpu,
                min_memory_gb=args.min_memory_gb,
                min_disk_free_gb=args.min_disk_free_gb,
            )
            if attestation["status"] != "pass":
                raise RemoteLabError("remote attestation must pass before deployment")
            payload = deploy_remote_inventory(
                inventory,
                compose_text=args.compose.read_text(encoding="utf-8"),
                api_key=os.environ.get("WAVEMIND_REMOTE_API_KEY", ""),
                postgres_password=os.environ.get("WAVEMIND_REMOTE_POSTGRES_PASSWORD", ""),
            )
        else:
            payload = probe_public_regions(
                inventory,
                api_key=os.environ.get("WAVEMIND_REMOTE_API_KEY"),
            )
        _write(args.output, payload)
        if args.manifest_output:
            _write(args.manifest_output, inventory.active_active_manifest())
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("status") in {"pass", "ready"} else 1
    except (OSError, ValueError, json.JSONDecodeError, RemoteLabError) as exc:
        print(f"remote-lab: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
