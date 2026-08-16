from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import uuid
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
from wavemind.upgrade import UpgradeError, UpgradeOptions, run_upgrade, verify_release_artifact


SCHEMA = "wavemind.upgrade_docker_compose.v1"


def _run(command: list[str], *, cwd: Path | None = None, timeout: float = 300) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _compose(root: Path, *args: str) -> str:
    return _run(
        [
            "docker",
            "compose",
            "--env-file",
            str(root / ".env"),
            "-f",
            str(root / "docker-compose.yml"),
            *args,
        ],
        cwd=root,
    )


def _seed_script() -> str:
    return """
from wavemind import (
    ExperienceKind, ExperienceRecord, ExperienceSource, ExperienceStatus,
    SQLiteExperienceStore, TrustClass, WaveMind,
)
mind = WaveMind(db_path='/data/wavemind.sqlite3')
try:
    kept = mind.remember(
        'Docker Compose upgrades preserve this memory.',
        namespace='tenant:upgrade:compose',
        metadata={'fixture': 'real-container-recreate'},
        ttl_seconds=7200,
    )
    removed = mind.remember(
        'Docker Compose upgrades must not resurrect this memory.',
        namespace='tenant:upgrade:compose',
    )
    assert mind.forget(removed, namespace='tenant:upgrade:compose') == 1
finally:
    mind.close()
record = ExperienceRecord.create(
    kind=ExperienceKind.PROCEDURE,
    title='Docker Compose upgrade fixture',
    content='Recreate the service without losing Verified Experience.',
    source=ExperienceSource(
        provider='upgrade-admission',
        source_type='operator_verification',
        source_id='docker-compose',
    ),
    namespace='tenant:upgrade:compose',
    confidence=1.0,
    trust=TrustClass.VERIFIED_OPERATOR,
    status=ExperienceStatus.ACTIVE,
)
with SQLiteExperienceStore('/data/wavemind-experience.sqlite3') as store:
    stored = store.put(record)
print(kept, removed, stored.id)
"""


def _state_script(expected_version: str) -> str:
    return f"""
import json, sqlite3, wavemind
assert wavemind.__version__ == {expected_version!r}, wavemind.__version__
a=sqlite3.connect('/data/wavemind.sqlite3')
b=sqlite3.connect('/data/wavemind-experience.sqlite3')
memories=a.execute('SELECT id,text,namespace,metadata,expires_at FROM memories ORDER BY id').fetchall()
experiences=b.execute('SELECT id,namespace,trust,status FROM experience_records ORDER BY id').fetchall()
a.close(); b.close()
assert len(memories)==1, memories
assert memories[0][1]=='Docker Compose upgrades preserve this memory.'
assert memories[0][2]=='tenant:upgrade:compose'
assert json.loads(memories[0][3])['fixture']=='real-container-recreate'
assert memories[0][4] is not None
assert len(experiences)==1, experiences
assert experiences[0][1]=='tenant:upgrade:compose'
assert experiences[0][2]=='verified_operator'
assert experiences[0][3]=='active'
print(json.dumps({{'version':wavemind.__version__,'memories':len(memories),'experiences':len(experiences)}}))
"""


def _container_id(root: Path) -> str:
    return _compose(root, "ps", "-q", "wavemind")


def run_docker_evidence(
    *,
    candidate_image: str,
    candidate_wheel: Path,
    candidate_sha256: str,
    old_image: str,
    expected_source_sha: str,
    work_root: Path | None,
) -> dict[str, object]:
    _name, parsed_version, _build, _tags = parse_wheel_filename(candidate_wheel.name)
    artifact = verify_release_artifact(
        candidate_wheel,
        expected_version=str(parsed_version),
        expected_sha256=candidate_sha256,
        source_url="local-ci-build",
    )
    image_revision = _run(
        [
            "docker",
            "image",
            "inspect",
            candidate_image,
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        ]
    )
    if image_revision != expected_source_sha:
        raise RuntimeError(
            f"candidate image source SHA {image_revision!r} != {expected_source_sha}"
        )
    owned = None
    if work_root is None:
        owned = tempfile.TemporaryDirectory(prefix="wavemind-compose-upgrade-")
        root = Path(owned.name)
    else:
        root = work_root.resolve()
        root.mkdir(parents=True, exist_ok=False)
    registry_name = f"wavemind-upgrade-registry-{uuid.uuid4().hex[:10]}"
    registry_port = _free_port()
    target_image = f"localhost:{registry_port}/wavemind:{artifact.version}"
    try:
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                registry_name,
                "-p",
                f"127.0.0.1:{registry_port}:5000",
                "registry:2",
            ]
        )
        _run(["docker", "tag", candidate_image, target_image])
        _run(["docker", "push", target_image], timeout=600)
        (root / "data").mkdir()
        (root / "backups").mkdir()
        (root / "docker-compose.yml").write_text(
            """services:
  wavemind:
    image: ${WAVEMIND_IMAGE}
    command: ["sleep", "infinity"]
    environment:
      WAVEMIND_DB: /data/wavemind.sqlite3
      WAVEMIND_EXPERIENCE_DB: /data/wavemind-experience.sqlite3
      WAVEMIND_BACKUP_ROOT: /backups
    volumes:
      - ./data:/data
      - ./backups:/backups
""",
            encoding="utf-8",
        )
        (root / ".env").write_text(f"WAVEMIND_IMAGE={old_image}\n", encoding="utf-8")
        _compose(root, "up", "-d", "--wait", "wavemind")
        first_container = _container_id(root)
        _compose(root, "exec", "-T", "wavemind", "python", "-c", _seed_script())
        source_version = _compose(root, "exec", "-T", "wavemind", "python", "-c", "import wavemind; print(wavemind.__version__)")
        options = UpgradeOptions(
            core_db=root / "data" / "wavemind.sqlite3",
            experience_db=root / "data" / "wavemind-experience.sqlite3",
            target_artifact=artifact.path,
            expected_sha256=artifact.sha256,
            mode="docker-compose",
            backup_dir=root / "backups",
            state_dir=root / "upgrade-state",
            config_paths=(root / ".env",),
            compose_file=root / "docker-compose.yml",
            compose_env_file=root / ".env",
            target_image=target_image,
            failure_phase="health",
        )
        rollback_error = None
        try:
            run_upgrade(options)
        except UpgradeError as exc:
            rollback_error = str(exc)
        rollback_journal = json.loads(
            (root / "upgrade-state" / "journal.json").read_text(encoding="utf-8")
        )
        rollback_container = _container_id(root)
        rollback_version = _compose(
            root,
            "exec",
            "-T",
            "wavemind",
            "python",
            "-c",
            "import wavemind; print(wavemind.__version__)",
        )
        rollback_state = json.loads(
            _compose(root, "exec", "-T", "wavemind", "python", "-c", _state_script(source_version))
        )
        rollback_passed = (
            rollback_error is not None
            and rollback_journal.get("status") == "rolled_back"
            and rollback_version == source_version
            and (root / ".env").read_text(encoding="utf-8").strip()
            == f"WAVEMIND_IMAGE={old_image}"
            and rollback_state["memories"] == 1
            and rollback_state["experiences"] == 1
        )
        success = run_upgrade(
            UpgradeOptions(**{**options.__dict__, "failure_phase": None})
        )
        target_container = _container_id(root)
        target_state = json.loads(
            _compose(root, "exec", "-T", "wavemind", "python", "-c", _state_script(artifact.version))
        )
        checks = {
            "candidate_image_exact_source_sha": image_revision == expected_source_sha,
            "immutable_target_digest": bool(success.image_digest)
            and str(success.image_digest).startswith("sha256:"),
            "failed_health_rolled_back": rollback_passed,
            "previous_container_recreated": first_container != rollback_container,
            "target_container_recreated": rollback_container != target_container,
            "core_state_preserved": target_state["memories"] == 1,
            "experience_state_preserved": target_state["experiences"] == 1,
            "forgotten_state_preserved": target_state["memories"] == 1,
            "target_version_running": target_state["version"] == artifact.version,
            "compose_env_activated": (root / ".env").read_text(encoding="utf-8").strip()
            == f"WAVEMIND_IMAGE={target_image}",
            "upgrade_parity": success.parity,
        }
        report = {
            "schema": SCHEMA,
            "status": "admitted" if all(checks.values()) else "blocked",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_sha": repository_commit(PROJECT_ROOT),
            "expected_source_sha": expected_source_sha,
            "environment": execution_environment(profile="upgrade-docker-compose"),
            "inputs": {
                "old_image": old_image,
                "candidate_image": candidate_image,
                "candidate_wheel": artifact.filename,
                "candidate_sha256": artifact.sha256,
                "expected_source_sha": expected_source_sha,
            },
            "candidate": {
                "wheel": artifact.as_dict(),
                "image": candidate_image,
                "image_revision": image_revision,
                "published_test_image": target_image,
                "digest": success.image_digest,
            },
            "source_version": source_version,
            "container_ids": {
                "before": first_container,
                "after_rollback": rollback_container,
                "after_success": target_container,
            },
            "checks": checks,
            "rollback": {
                "error": rollback_error,
                "journal_status": rollback_journal.get("status"),
                "version": rollback_version,
                "state": rollback_state,
            },
            "success": success.as_dict(),
            "target_state": target_state,
            "source_manifest": build_source_manifest(
                PROJECT_ROOT,
                [
                    "Dockerfile",
                    "docker-compose.yml",
                    "wavemind/upgrade.py",
                    "wavemind/schema_migrations.py",
                    "benchmarks/upgrade_docker_compose.py",
                ],
            ),
        }
        return attach_artifact_integrity(report)
    finally:
        subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(root / ".env"),
                "-f",
                str(root / "docker-compose.yml"),
                "down",
                "--remove-orphans",
            ],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=120,
        )
        subprocess.run(
            ["docker", "rm", "-f", registry_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
        subprocess.run(
            ["docker", "image", "rm", target_image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
        if owned is not None:
            owned.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-image", required=True)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--old-image", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = args.candidate_sha256 or hashlib.sha256(args.candidate_wheel.read_bytes()).hexdigest()
    report = run_docker_evidence(
        candidate_image=args.candidate_image,
        candidate_wheel=args.candidate_wheel.resolve(),
        candidate_sha256=digest,
        old_image=args.old_image,
        expected_source_sha=args.expected_source_sha,
        work_root=args.work_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "admitted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
