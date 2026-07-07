from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import build_postgres_pitr_plan


def run_profile(*, generated_at: str = "2026-07-07T00:00:00Z") -> dict[str, object]:
    plan = build_postgres_pitr_plan(generated_at=generated_at)
    payload = plan.as_dict()
    return {
        "schema": "wavemind.postgres_pitr_profile.v1",
        "generated_at": generated_at,
        "status": payload["status"],
        "environment_status": payload["environment_status"],
        "profile": payload,
        "summary": {
            "required_env": payload["required_env"],
            "missing_env": payload["missing_env"],
            "checks": payload["validation"]["checks"],
            "command_count": len(payload["commands"]),
            "retention_hours": payload["retention_hours"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/postgres_pitr_plan.json"),
    )
    parser.add_argument("--generated-at", default="2026-07-07T00:00:00Z")
    args = parser.parse_args()

    payload = run_profile(generated_at=args.generated_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "ready" else 4


if __name__ == "__main__":
    raise SystemExit(main())
