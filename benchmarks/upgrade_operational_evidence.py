from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    execution_environment,
    repository_commit,
)


SCHEMA = "wavemind.upgrade_operational_evidence.v1"


def run_operational_evidence() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="wavemind-upgrade-junit-") as raw:
        junit = Path(raw) / "upgrade.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_upgrade.py",
            f"--junitxml={junit}",
        ]
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=600,
        )
        cases: list[dict[str, object]] = []
        if junit.exists():
            root = ET.parse(junit).getroot()
            for case in root.iter("testcase"):
                failed = case.find("failure") is not None or case.find("error") is not None
                skipped = case.find("skipped") is not None
                cases.append(
                    {
                        "name": case.attrib.get("name"),
                        "classname": case.attrib.get("classname"),
                        "seconds": float(case.attrib.get("time", "0")),
                        "status": "failed" if failed else "skipped" if skipped else "passed",
                    }
                )
    checks = {
        "pytest_exit_zero": result.returncode == 0,
        "all_cases_passed": bool(cases) and all(row["status"] == "passed" for row in cases),
        "minimum_matrix_size": len(cases) >= 20,
    }
    report = {
        "schema": SCHEMA,
        "status": "admitted" if all(checks.values()) else "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": repository_commit(PROJECT_ROOT),
        "environment": execution_environment(profile="upgrade-operational"),
        "inputs": {"command": command, "timeout_seconds": 600},
        "command": command,
        "checks": checks,
        "metrics": {
            "cases": len(cases),
            "passed": sum(row["status"] == "passed" for row in cases),
            "failed": sum(row["status"] == "failed" for row in cases),
            "skipped": sum(row["status"] == "skipped" for row in cases),
        },
        "cases": cases,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
        "source_manifest": build_source_manifest(
            PROJECT_ROOT,
            [
                "pyproject.toml",
                "wavemind/upgrade.py",
                "wavemind/schema_migrations.py",
                "wavemind/cli.py",
                "tests/test_upgrade.py",
                "benchmarks/upgrade_operational_evidence.py",
            ],
        ),
    }
    return attach_artifact_integrity(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_operational_evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "admitted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
