from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from packaging.utils import parse_wheel_filename

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    execution_environment,
    repository_commit,
)
from wavemind.upgrade import verify_release_artifact


SCHEMA = "wavemind.upgrade_python_cross_version.v1"


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float = 600,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
        timeout=timeout,
    )


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _seed_script(core: Path, experience: Path) -> str:
    return f"""
from wavemind import (
    ExperienceKind, ExperienceRecord, ExperienceSource, ExperienceStatus,
    SQLiteExperienceStore, TrustClass, WaveMind,
)
mind = WaveMind(db_path={str(core)!r})
try:
    kept = mind.remember(
        'Cross-version upgrades preserve this memory.',
        namespace='tenant:upgrade:cross-version',
        metadata={{'fixture': 'published-release'}},
        ttl_seconds=7200,
    )
    removed = mind.remember(
        'Cross-version upgrades must not resurrect this memory.',
        namespace='tenant:upgrade:cross-version',
    )
    assert mind.forget(removed, namespace='tenant:upgrade:cross-version') == 1
finally:
    mind.close()
record = ExperienceRecord.create(
    kind=ExperienceKind.PROCEDURE,
    title='Published release upgrade fixture',
    content='Preserve verified experience across package replacement.',
    source=ExperienceSource(
        provider='upgrade-admission',
        source_type='operator_verification',
        source_id='cross-version',
    ),
    namespace='tenant:upgrade:cross-version',
    confidence=1.0,
    trust=TrustClass.VERIFIED_OPERATOR,
    status=ExperienceStatus.ACTIVE,
)
with SQLiteExperienceStore({str(experience)!r}) as store:
    stored = store.put(record)
print(kept, removed, stored.id)
"""


def _postcheck_script(core: Path, experience: Path, target_version: str) -> str:
    return f"""
import json, sqlite3, wavemind
from wavemind import WaveMind
assert wavemind.__version__ == {target_version!r}, wavemind.__version__
a = sqlite3.connect({str(core)!r})
b = sqlite3.connect({str(experience)!r})
rows = a.execute(
    "SELECT id, text, namespace, metadata, expires_at FROM memories ORDER BY id"
).fetchall()
experiences = b.execute(
    "SELECT id, namespace, trust, status FROM experience_records ORDER BY id"
).fetchall()
core_schema = a.execute(
    "SELECT MAX(version) FROM wavemind_schema_migrations WHERE component='core'"
).fetchone()[0]
experience_schema = b.execute(
    "SELECT MAX(version) FROM wavemind_schema_migrations WHERE component='experience'"
).fetchone()[0]
a.close(); b.close()
assert len(rows) == 1, rows
assert rows[0][1] == 'Cross-version upgrades preserve this memory.'
assert rows[0][2] == 'tenant:upgrade:cross-version'
assert json.loads(rows[0][3])['fixture'] == 'published-release'
assert rows[0][4] is not None
assert len(experiences) == 1, experiences
assert experiences[0][1] == 'tenant:upgrade:cross-version'
assert experiences[0][2] == 'verified_operator'
assert experiences[0][3] == 'active'
assert core_schema == 1 and experience_schema == 1
mind = WaveMind(db_path={str(core)!r})
try:
    hits = mind.query('preserve cross-version memory', namespace='tenant:upgrade:cross-version', top_k=1)
    assert hits and hits[0].id == rows[0][0]
    assert mind.feedback(hits[0].id, namespace='tenant:upgrade:cross-version', useful=True)
    probe = mind.remember('Post-upgrade runtime probe', namespace='tenant:upgrade:cross-version')
    assert mind.query('runtime probe', namespace='tenant:upgrade:cross-version', top_k=1)
    assert mind.forget(probe, namespace='tenant:upgrade:cross-version') == 1
finally:
    mind.close()
print(json.dumps({{
    'installed_version': wavemind.__version__,
    'active_memories': len(rows),
    'active_experiences': len(experiences),
    'core_schema': core_schema,
    'experience_schema': experience_schema,
    'remember_query_feedback': True,
}}))
"""


def _runtime_probe_script(core: Path, expected_version: str, phase: str) -> str:
    return f"""
import json, wavemind
from wavemind import WaveMind
assert wavemind.__version__ == {expected_version!r}, wavemind.__version__
mind = WaveMind(db_path={str(core)!r})
try:
    hits = mind.query('preserve cross-version memory', namespace='tenant:upgrade:cross-version', top_k=1)
    assert hits
    assert mind.feedback(hits[0].id, namespace='tenant:upgrade:cross-version', useful=True)
    probe = mind.remember({('Runtime probe ' + phase)!r}, namespace='tenant:upgrade:cross-version')
    assert mind.query({('Runtime probe ' + phase)!r}, namespace='tenant:upgrade:cross-version', top_k=1)
    assert mind.forget(probe, namespace='tenant:upgrade:cross-version') == 1
finally:
    mind.close()
print(json.dumps({{'version': wavemind.__version__, 'phase': {phase!r}, 'passed': True}}))
"""


def _installed_version(python: Path, *, cwd: Path) -> str:
    result = _run(
        [str(python), "-I", "-c", "import wavemind; print(wavemind.__version__)"],
        cwd=cwd,
    )
    return result.stdout.strip()


def _run_fixture(
    *,
    source_version: str,
    candidate_wheel: Path,
    candidate_sha256: str,
    target_version: str,
    root: Path,
    rollback_probe: bool,
) -> dict[str, object]:
    fixture_root = root / f"from-{source_version}"
    venv = fixture_root / "venv"
    state = fixture_root / "state"
    fixture_root.mkdir(parents=True)
    state.mkdir()
    core = state / "core.sqlite3"
    experience = state / "experience.sqlite3"
    _run([sys.executable, "-m", "venv", str(venv)], cwd=fixture_root)
    python = _venv_python(venv)
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            f"wavemind=={source_version}",
            "packaging>=24",
            "psutil>=5.9",
        ],
        cwd=fixture_root,
    )
    seed = _run(
        [str(python), "-I", "-c", _seed_script(core, experience)],
        cwd=fixture_root,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    base_command = [
        str(python),
        "-m",
        "wavemind",
        "--db",
        str(core),
        "upgrade",
        "--experience-db",
        str(experience),
        "--artifact",
        str(candidate_wheel),
        "--expected-sha256",
        candidate_sha256,
        "--backup-dir",
        str(fixture_root / "backups"),
        "--state-dir",
        str(fixture_root / "upgrade"),
        "--json",
    ]
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    rollback: dict[str, object] | None = None
    if rollback_probe:
        failed = _run(
            [*base_command[:-1], "--inject-failure", "health", "--json"],
            cwd=fixture_root,
            env=env,
            check=False,
        )
        journal = json.loads(
            (fixture_root / "upgrade" / "journal.json").read_text(encoding="utf-8")
        )
        restored_version = _installed_version(python, cwd=fixture_root)
        rollback_runtime = json.loads(
            _run(
                [
                    str(python),
                    "-I",
                    "-c",
                    _runtime_probe_script(core, source_version, "rollback"),
                ],
                cwd=fixture_root,
                env=clean_env,
            ).stdout
        )
        rollback = {
            "returncode": failed.returncode,
            "status": journal.get("status"),
            "installed_version": restored_version,
            "runtime": rollback_runtime,
            "passed": failed.returncode != 0
            and journal.get("status") == "rolled_back"
            and restored_version == source_version
            and rollback_runtime.get("passed") is True,
        }
    completed = _run(base_command, cwd=fixture_root, env=env)
    report = json.loads(completed.stdout)
    postcheck = _run(
        [str(python), "-I", "-c", _postcheck_script(core, experience, target_version)],
        cwd=fixture_root,
        env=clean_env,
    )
    checked = json.loads(postcheck.stdout)
    return {
        "source_version": source_version,
        "target_version": target_version,
        "seed": seed.stdout.strip().split(),
        "upgrade_status": report.get("status"),
        "parity": report.get("parity"),
        "schema_versions": report.get("schema_versions"),
        "postcheck": checked,
        "rollback_probe": rollback,
        "passed": report.get("status") == "complete"
        and report.get("parity") is True
        and checked.get("installed_version") == target_version
        and checked.get("active_memories") == 1
        and checked.get("active_experiences") == 1
        and checked.get("remember_query_feedback") is True
        and (rollback is None or rollback.get("passed") is True),
    }


def run_cross_version_evidence(
    *,
    candidate_wheel: Path,
    candidate_sha256: str,
    source_versions: list[str],
    work_root: Path | None,
) -> dict[str, object]:
    _name, parsed_version, _build, _tags = parse_wheel_filename(candidate_wheel.name)
    artifact = verify_release_artifact(
        candidate_wheel,
        expected_version=str(parsed_version),
        expected_sha256=candidate_sha256,
        source_url="local-ci-build",
    )
    owned = None
    if work_root is None:
        owned = tempfile.TemporaryDirectory(prefix="wavemind-cross-version-")
        root = Path(owned.name)
    else:
        root = work_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
    try:
        fixtures = [
            _run_fixture(
                source_version=version,
                candidate_wheel=artifact.path,
                candidate_sha256=artifact.sha256,
                target_version=artifact.version,
                root=root,
                rollback_probe=index == len(source_versions) - 1,
            )
            for index, version in enumerate(source_versions)
        ]
    finally:
        if owned is not None:
            owned.cleanup()
    report = {
        "schema": SCHEMA,
        "status": "admitted" if fixtures and all(row["passed"] for row in fixtures) else "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": repository_commit(PROJECT_ROOT),
        "environment": execution_environment(profile="upgrade-python-cross-version"),
        "inputs": {
            "source_versions": list(source_versions),
            "candidate_wheel": artifact.filename,
            "candidate_sha256": artifact.sha256,
        },
        "candidate": artifact.as_dict(),
        "fixtures": fixtures,
        "source_manifest": build_source_manifest(
            PROJECT_ROOT,
            [
                "pyproject.toml",
                "wavemind/upgrade.py",
                "wavemind/schema_migrations.py",
                "wavemind/cli.py",
                "benchmarks/upgrade_python_cross_version.py",
            ],
        ),
    }
    return attach_artifact_integrity(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--source-version", action="append", required=True)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = args.candidate_sha256 or hashlib.sha256(args.candidate_wheel.read_bytes()).hexdigest()
    report = run_cross_version_evidence(
        candidate_wheel=args.candidate_wheel.resolve(),
        candidate_sha256=digest,
        source_versions=args.source_version,
        work_root=args.work_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "admitted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
