from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

import wavemind.upgrade as upgrade
import wavemind.cli as cli
from wavemind import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    HashingTextEncoder,
    SQLiteExperienceStore,
    TrustClass,
    WaveMind,
)
from wavemind.schema_migrations import (
    CORE_COMPONENT,
    EXPERIENCE_COMPONENT,
    MIGRATION_TABLE,
    read_schema_version,
)
from wavemind.upgrade import (
    UpgradeArtifactError,
    UpgradeBlocked,
    UpgradeError,
    UpgradeJournal,
    UpgradeOptions,
    create_upgrade_backup,
    database_inventory,
    restore_upgrade_backup,
    run_upgrade,
    upgrade_lock,
    verify_upgrade_backup,
)


def _wheel(path: Path, version: str) -> tuple[Path, str]:
    dist_info = f"wavemind-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            "\n".join(
                [
                    "Metadata-Version: 2.1",
                    "Name: wavemind",
                    f"Version: {version}",
                    "",
                ]
            ),
        )
        archive.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _experience() -> ExperienceRecord:
    return ExperienceRecord.create(
        kind=ExperienceKind.PROCEDURE,
        title="Preserve release state",
        content="Back up, migrate, verify, and roll back on any failed check.",
        source=ExperienceSource(
            provider="test",
            source_type="operator_verification",
            source_id="upgrade-proof",
        ),
        namespace="tenant:a:upgrade",
        confidence=1.0,
        trust=TrustClass.VERIFIED_OPERATOR,
        status=ExperienceStatus.ACTIVE,
    )


def _state(root: Path, *, legacy: bool = True) -> tuple[Path, Path, int, str]:
    core = root / "core.sqlite3"
    experience = root / "experience.sqlite3"
    mind = WaveMind(db_path=core, encoder=HashingTextEncoder(vector_dim=32))
    try:
        kept_id = mind.remember(
            "Keep this memory across every upgrade",
            namespace="tenant:a:upgrade",
            metadata={"source": "test", "revision": 7},
            ttl_seconds=3600,
        )
        forgotten_id = mind.remember(
            "This memory must stay forgotten",
            namespace="tenant:a:upgrade",
        )
        assert mind.forget(forgotten_id, namespace="tenant:a:upgrade") == 1
    finally:
        mind.close()
    with SQLiteExperienceStore(experience) as store:
        record = store.put(_experience())
    if legacy:
        for path in (core, experience):
            connection = sqlite3.connect(path)
            try:
                connection.execute(f"DROP TABLE {MIGRATION_TABLE}")
                connection.commit()
            finally:
                connection.close()
    return core, experience, kept_id, record.id


def _options(
    root: Path,
    core: Path,
    experience: Path,
    wheel: Path,
    digest: str,
    **overrides,
) -> UpgradeOptions:
    values = {
        "core_db": core,
        "experience_db": experience,
        "target_artifact": wheel,
        "expected_sha256": digest,
        "backup_dir": root / "backups",
        "state_dir": root / "upgrade-state",
        # Unit tests validate transaction semantics in the source checkout.
        # Clean-venv admission separately exercises the isolated installed-wheel
        # health command used by real upgrades.
        "health_command": [sys.executable, "-c", "print('upgrade-health-ok')"],
    }
    values.update(overrides)
    current_artifact = values.get("current_artifact")
    if current_artifact is not None and "current_expected_sha256" not in values:
        values["current_expected_sha256"] = hashlib.sha256(
            Path(current_artifact).read_bytes()
        ).hexdigest()
    return UpgradeOptions(**values)


@pytest.fixture(autouse=True)
def _stable_unit_installed_version(monkeypatch):
    monkeypatch.setattr(upgrade, "_installed_version", lambda: "2.12.1")


def _completed(command, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_production_command_runner_applies_a_hard_timeout(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return _completed(command)

    monkeypatch.setattr(upgrade.subprocess, "run", fake_run)
    upgrade._run_command(["example", "command"])

    assert captured["timeout"] == upgrade.DEFAULT_COMMAND_TIMEOUT_SECONDS


def test_process_preflight_never_queries_docker_command_line(tmp_path, monkeypatch):
    protected = tmp_path / "core.sqlite3"
    protected.write_bytes(b"state")
    queried: list[str] = []

    class Process:
        def __init__(self, pid: int, name: str, command: list[str]):
            self.pid = pid
            self.info = {"pid": pid, "name": name}
            self._command = command

        def cmdline(self):
            queried.append(str(self.info["name"]))
            if "docker" in str(self.info["name"]).lower():
                raise AssertionError("Docker command line must not be queried")
            return self._command

    class Psutil:
        AccessDenied = OSError
        NoSuchProcess = OSError

        @staticmethod
        def process_iter(attrs):
            assert attrs == ["pid", "name"]
            return [
                Process(9001, "Docker Desktop.exe", ["docker"]),
                Process(9002, "python.exe", ["python", "-m", "wavemind", str(protected)]),
            ]

    monkeypatch.setitem(sys.modules, "psutil", Psutil)
    blockers = upgrade._open_processes([protected])

    assert queried == ["python.exe"]
    assert [row["pid"] for row in blockers] == [9002]


def test_process_liveness_probe_never_signals_the_process(monkeypatch):
    class Psutil:
        @staticmethod
        def pid_exists(pid):
            return pid == 123

    monkeypatch.setitem(sys.modules, "psutil", Psutil)

    def fail_kill(*_args):
        pytest.fail("process liveness probes must not signal the process")

    monkeypatch.setattr(upgrade.os, "kill", fail_kill)

    assert upgrade._process_alive(123) is True
    assert upgrade._process_alive(456) is False


def test_same_version_upgrade_adopts_legacy_ledgers_and_preserves_all_state(tmp_path):
    core, experience, memory_id, experience_id = _state(tmp_path)
    config = tmp_path / "policy.json"
    config.write_text('{"policy":"strict","unknown_key":true}\n', encoding="utf-8")
    object_manifest = tmp_path / "objects.json"
    object_manifest.write_text('{"objects":["s3://bucket/asset"]}\n', encoding="utf-8")
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    before_core = database_inventory(core)
    before_experience = database_inventory(experience)

    report = run_upgrade(
        _options(
            tmp_path,
            core,
            experience,
            wheel,
            digest,
            config_paths=(config,),
            object_manifest_paths=(object_manifest,),
        )
    )

    assert report.status == "complete"
    assert report.parity is True
    assert report.schema_versions == {"core": 1, "experience": 1}
    assert database_inventory(core) == before_core
    assert database_inventory(experience) == before_experience
    assert config.read_text(encoding="utf-8") == '{"policy":"strict","unknown_key":true}\n'
    assert object_manifest.read_text(encoding="utf-8") == '{"objects":["s3://bucket/asset"]}\n'
    assert verify_upgrade_backup(Path(report.backup_path))["source_version"] == "2.12.1"

    mind = WaveMind(db_path=core, encoder=HashingTextEncoder(vector_dim=32))
    try:
        assert mind.store.get(memory_id) is not None
        rows = mind.store.list(namespace="tenant:a:upgrade", include_expired=True)
        assert [row.id for row in rows] == [memory_id]
    finally:
        mind.close()
    with SQLiteExperienceStore(experience) as store:
        assert store.get(experience_id) is not None
        assert read_schema_version(store.conn, EXPERIENCE_COMPONENT) == 1


@pytest.mark.parametrize("source_version", ["2.10.0", "2.11.0"])
def test_cross_version_n_minus_two_and_n_minus_one_use_verified_rollback_wheels(
    tmp_path,
    monkeypatch,
    source_version,
):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    target_wheel, target_digest = _wheel(
        tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1"
    )
    current_wheel, _current_digest = _wheel(
        tmp_path / f"wavemind-{source_version}-py3-none-any.whl", source_version
    )
    monkeypatch.setattr(upgrade, "_installed_version", lambda: source_version)
    commands: list[list[str]] = []

    def runner(command, cwd=None):
        commands.append(list(command))
        return _completed(command, '{"integrity":["ok","ok"]}\n')

    report = run_upgrade(
        _options(
            tmp_path,
            core,
            experience,
            target_wheel,
            target_digest,
            current_artifact=current_wheel,
        ),
        runner=runner,
    )

    assert report.status == "complete"
    installs = [command for command in commands if "pip" in command]
    assert len(installs) == 1
    assert str(target_wheel.resolve()) in installs[0]


def test_repeated_upgrade_is_idempotent(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    options = _options(tmp_path, core, experience, wheel, digest)

    first = run_upgrade(options)
    first_inventory = (database_inventory(core), database_inventory(experience))
    second = run_upgrade(options)

    assert first.status == second.status == "complete"
    assert (database_inventory(core), database_inventory(experience)) == first_inventory
    assert len(list((tmp_path / "backups").glob("*.wavemind-upgrade.zip"))) >= 1


def test_interrupted_journal_is_recovered_before_retry(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    options = _options(tmp_path, core, experience, wheel, digest)
    options.state_dir.mkdir(parents=True)
    backup = create_upgrade_backup(
        options,
        tmp_path / "interrupted.zip",
        source_version="2.12.1",
        target_version="2.12.1",
    )
    journal = UpgradeJournal.create(
        options.state_dir / "journal.json",
        source_version="2.12.1",
        target_version="2.12.1",
        mode="python",
        options=options,
    )
    journal.payload["backup_path"] = str(backup)
    journal.event("data_activated")
    connection = sqlite3.connect(core)
    try:
        connection.execute("DELETE FROM memories")
        connection.commit()
    finally:
        connection.close()

    report = run_upgrade(options)

    assert report.status == "complete"
    assert database_inventory(core)["tables"]["memories"]["rows"] == 1


def test_active_writer_blocks_before_backup(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    connection = sqlite3.connect(core, isolation_level=None)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(UpgradeError, match="active writer"):
            run_upgrade(_options(tmp_path, core, experience, wheel, digest))
    finally:
        connection.execute("ROLLBACK")
        connection.close()
    assert not list((tmp_path / "backups").glob("*.zip"))


def test_disk_full_preflight_blocks_without_touching_state(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    before = (core.read_bytes(), experience.read_bytes())

    with pytest.raises(UpgradeError, match="insufficient disk space"):
        run_upgrade(
            _options(
                tmp_path,
                core,
                experience,
                wheel,
                digest,
                minimum_free_bytes=2**63,
            )
        )

    assert (core.read_bytes(), experience.read_bytes()) == before


def test_checksum_mismatch_is_fail_closed(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, _digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")

    with pytest.raises(UpgradeError, match="checksum mismatch"):
        run_upgrade(_options(tmp_path, core, experience, wheel, "0" * 64))

    assert not list((tmp_path / "backups").glob("*.zip"))


def test_docker_local_wheel_checksum_is_verified_before_docker_mutation(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, _digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  wavemind:\n    image: ${WAVEMIND_IMAGE:-old:image}\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def runner(command, cwd=None):
        commands.append(list(command))
        return _completed(command)

    with pytest.raises(UpgradeError, match="checksum mismatch"):
        run_upgrade(
            _options(
                tmp_path,
                core,
                experience,
                wheel,
                "0" * 64,
                mode="docker-compose",
                compose_file=compose,
                compose_env_file=tmp_path / ".env",
            ),
            runner=runner,
        )

    assert commands == []


@pytest.mark.parametrize("failure", ["staged_migration", "data_activation", "health"])
def test_failure_injection_restores_both_databases_and_config(tmp_path, failure):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    config = tmp_path / "config.json"
    config.write_text('{"mode":"before"}\n', encoding="utf-8")
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    before = (database_inventory(core), database_inventory(experience), config.read_bytes())

    with pytest.raises(UpgradeError, match="rolled back"):
        run_upgrade(
            _options(
                tmp_path,
                core,
                experience,
                wheel,
                digest,
                config_paths=(config,),
                failure_phase=failure,
            )
        )

    assert (database_inventory(core), database_inventory(experience), config.read_bytes()) == before
    journal = json.loads((tmp_path / "upgrade-state" / "journal.json").read_text())
    assert journal["status"] == "rolled_back"


def test_incompatible_future_schema_is_rolled_back(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path, legacy=False)
    connection = sqlite3.connect(core)
    try:
        connection.execute(
            f"INSERT INTO {MIGRATION_TABLE} "
            "(component, version, release, checksum, applied_at) VALUES (?, ?, ?, ?, ?)",
            (CORE_COMPONENT, 99, "future", "future", 0.0),
        )
        connection.commit()
    finally:
        connection.close()
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")

    with pytest.raises(UpgradeError, match="version gap|newer"):
        run_upgrade(_options(tmp_path, core, experience, wheel, digest))

    connection = sqlite3.connect(core)
    try:
        assert read_schema_version(connection, CORE_COMPONENT) == 99
    finally:
        connection.close()


def test_tampered_upgrade_backup_is_rejected(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    options = _options(tmp_path, core, experience, wheel, digest)
    archive = create_upgrade_backup(
        options,
        tmp_path / "backup.zip",
        source_version="2.12.1",
        target_version="2.12.1",
    )
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == "core.sqlite3":
                payload += b"tampered"
            target.writestr(name, payload)

    with pytest.raises(UpgradeArtifactError, match="size mismatch"):
        restore_upgrade_backup(tampered)


def test_interrupted_recovery_rejects_backup_whose_outer_digest_changed(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    options = _options(tmp_path, core, experience, wheel, digest)
    backup = create_upgrade_backup(
        options,
        tmp_path / "backup.zip",
        source_version="2.12.1",
        target_version="2.12.1",
    )
    journal = UpgradeJournal.create(
        options.state_dir / "journal.json",
        source_version="2.12.1",
        target_version="2.12.1",
        mode="python",
        options=options,
    )
    journal.payload["backup_path"] = str(backup)
    journal.payload["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    journal.event("data_activated")
    with backup.open("ab") as destination:
        destination.write(b"tampered-after-journal")

    with pytest.raises(UpgradeBlocked, match="checksum does not match the journal"):
        upgrade._recover_interrupted(journal, options=options, runner=upgrade._run_command)


def test_docker_compose_recreates_container_and_pins_target_image(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  wavemind:\n    image: ${WAVEMIND_IMAGE:-old:image}\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    commands: list[list[str]] = []

    def runner(command, cwd=None):
        command = list(command)
        commands.append(command)
        if command[-2:] == ["config", "--images"]:
            if env.exists() and "WAVEMIND_IMAGE=" in env.read_text(encoding="utf-8"):
                image = env.read_text(encoding="utf-8").split("WAVEMIND_IMAGE=", 1)[1].splitlines()[0]
                return _completed(command, image + "\n")
            return _completed(command, "old:image\n")
        if "image" in command and "inspect" in command and "{{.Id}}" in command:
            return _completed(command, "sha256:" + "c" * 64 + "\n")
        if "image" in command and "inspect" in command:
            return _completed(command, '["ghcr.io/caspiang/wavemind@sha256:' + "a" * 64 + '"]\n')
        if "exec" in command:
            return _completed(command, "wavemind 2.12.1\n")
        return _completed(command)

    report = run_upgrade(
        _options(
            tmp_path,
            core,
            experience,
            wheel,
            digest,
            mode="docker-compose",
            compose_file=compose,
            compose_env_file=env,
            config_paths=(env,),
        ),
        runner=runner,
    )

    assert report.status == "complete"
    assert report.image_digest == "sha256:" + "a" * 64
    assert env.read_text(encoding="utf-8") == "WAVEMIND_IMAGE=ghcr.io/caspiang/wavemind:2.12.1\n"
    assert any("stop" in command for command in commands)
    assert any("--force-recreate" in command for command in commands)


def test_docker_failure_restores_absent_env_and_restarts_old_image(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  wavemind:\n    image: ${WAVEMIND_IMAGE:-old:image}\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    commands: list[list[str]] = []

    def runner(command, cwd=None):
        command = list(command)
        commands.append(command)
        if command[-2:] == ["config", "--images"]:
            image = "old:image"
            if env.exists():
                image = env.read_text(encoding="utf-8").split("=", 1)[1].strip()
            return _completed(command, image + "\n")
        if "image" in command and "inspect" in command and "{{.Id}}" in command:
            return _completed(command, "sha256:" + "d" * 64 + "\n")
        if "image" in command and "inspect" in command:
            return _completed(command, '["repo@sha256:' + "b" * 64 + '"]\n')
        if "exec" in command:
            return _completed(command, "wavemind 2.12.1\n")
        return _completed(command)

    with pytest.raises(UpgradeError, match="rolled back"):
        run_upgrade(
            _options(
                tmp_path,
                core,
                experience,
                wheel,
                digest,
                mode="docker-compose",
                compose_file=compose,
                compose_env_file=env,
                config_paths=(env,),
                failure_phase="health",
            ),
            runner=runner,
        )

    assert not env.exists()
    up_commands = [command for command in commands if "up" in command]
    assert len(up_commands) == 2
    health_commands = [
        command
        for command in commands
        if "exec" in command and "python" in command and "-c" in command
    ]
    assert len(health_commands) == 2
    assert all("WAVEMIND_DB" in command[-1] for command in health_commands)
    assert all("WAVEMIND_EXPERIENCE_DB" in command[-1] for command in health_commands)


def test_interrupted_docker_upgrade_restores_data_env_and_old_image_before_retry(
    tmp_path,
):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  wavemind:\n    image: ${WAVEMIND_IMAGE:-old:image}\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    env.write_text("WAVEMIND_IMAGE=old:image\nKEEP=unchanged\n", encoding="utf-8")
    options = _options(
        tmp_path,
        core,
        experience,
        wheel,
        digest,
        mode="docker-compose",
        compose_file=compose,
        compose_env_file=env,
        config_paths=(env,),
    )
    options.state_dir.mkdir(parents=True)
    backup = create_upgrade_backup(
        options,
        tmp_path / "interrupted-docker.zip",
        source_version="2.11.0",
        target_version="2.12.1",
    )
    journal = UpgradeJournal.create(
        options.state_dir / "journal.json",
        source_version="2.11.0",
        target_version="2.12.1",
        mode="docker-compose",
        options=options,
    )
    journal.payload.update(
        {
            "backup_path": str(backup),
            "previous_image": "old:image",
            "target_image": "new:image",
            "rollback_image": "wavemind-upgrade-rollback:interrupted",
        }
    )
    journal.event("data_activated")
    connection = sqlite3.connect(core)
    try:
        connection.execute("DELETE FROM memories")
        connection.commit()
    finally:
        connection.close()
    env.write_text("WAVEMIND_IMAGE=new:image\nKEEP=changed\n", encoding="utf-8")
    commands: list[list[str]] = []

    def runner(command, cwd=None):
        command = list(command)
        commands.append(command)
        if command[-2:] == ["config", "--images"]:
            image = env.read_text(encoding="utf-8").split("WAVEMIND_IMAGE=", 1)[1].splitlines()[0]
            return _completed(command, image + "\n")
        if "exec" in command and command[-1] == "--version":
            current = env.read_text(encoding="utf-8")
            version = "2.11.0" if "old:image" in current else "2.12.1"
            return _completed(command, f"wavemind {version}\n")
        if "exec" in command:
            return _completed(command, "upgrade-health-ok\n")
        if "image" in command and "inspect" in command and "{{.Id}}" in command:
            return _completed(command, "sha256:" + "c" * 64 + "\n")
        if "image" in command and "inspect" in command:
            return _completed(command, '["repo@sha256:' + "a" * 64 + '"]\n')
        return _completed(command)

    report = run_upgrade(options, runner=runner)

    assert report.status == "complete"
    assert database_inventory(core)["tables"]["memories"]["rows"] == 1
    assert env.read_text(encoding="utf-8") == (
        "WAVEMIND_IMAGE=ghcr.io/caspiang/wavemind:2.12.1\nKEEP=unchanged\n"
    )
    assert ["docker", "tag", "wavemind-upgrade-rollback:interrupted", "old:image"] in commands
    assert ["docker", "image", "rm", "wavemind-upgrade-rollback:interrupted"] in commands


def test_python_package_health_failure_reinstalls_verified_source_wheel(
    tmp_path,
    monkeypatch,
):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    target, target_digest = _wheel(
        tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1"
    )
    source, _source_digest = _wheel(
        tmp_path / "wavemind-2.11.0-py3-none-any.whl", "2.11.0"
    )
    monkeypatch.setattr(upgrade, "_installed_version", lambda: "2.11.0")
    installs: list[str] = []

    def runner(command, cwd=None):
        command = list(command)
        if "pip" in command:
            installs.append(command[-1])
            return _completed(command)
        return _completed(command, "health failed")

    with pytest.raises(UpgradeError, match="rolled back"):
        run_upgrade(
            _options(
                tmp_path,
                core,
                experience,
                target,
                target_digest,
                current_artifact=source,
                failure_phase="health",
            ),
            runner=runner,
        )

    assert installs == [str(target.resolve()), str(source.resolve())]


def test_python_installation_failure_reinstalls_verified_source_wheel(
    tmp_path,
    monkeypatch,
):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    target, target_digest = _wheel(
        tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1"
    )
    source, _source_digest = _wheel(
        tmp_path / "wavemind-2.11.0-py3-none-any.whl", "2.11.0"
    )
    monkeypatch.setattr(upgrade, "_installed_version", lambda: "2.11.0")
    installs: list[str] = []

    def runner(command, cwd=None):
        command = list(command)
        if "pip" in command:
            installs.append(command[-1])
            if command[-1] == str(target.resolve()):
                raise subprocess.CalledProcessError(1, command, stderr="install failed")
        return _completed(command)

    with pytest.raises(UpgradeError, match="rolled back"):
        run_upgrade(
            _options(
                tmp_path,
                core,
                experience,
                target,
                target_digest,
                current_artifact=source,
            ),
            runner=runner,
        )

    assert installs == [str(target.resolve()), str(source.resolve())]
    journal = json.loads((tmp_path / "upgrade-state" / "journal.json").read_text())
    assert journal["rollback_parity_verified"] is True


def test_offline_rollback_wheel_requires_expected_checksum(tmp_path, monkeypatch):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    target, target_digest = _wheel(
        tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1"
    )
    source, _source_digest = _wheel(
        tmp_path / "wavemind-2.11.0-py3-none-any.whl", "2.11.0"
    )
    monkeypatch.setattr(upgrade, "_installed_version", lambda: "2.11.0")
    options = _options(
        tmp_path,
        core,
        experience,
        target,
        target_digest,
        current_artifact=source,
    )

    with pytest.raises(UpgradeError, match="current-expected-sha256"):
        run_upgrade(
            UpgradeOptions(
                **{**options.__dict__, "current_expected_sha256": None}
            )
        )


def test_dry_run_does_not_create_or_change_databases(tmp_path):
    core = tmp_path / "missing-core.sqlite3"
    experience = tmp_path / "missing-experience.sqlite3"
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")

    report = run_upgrade(
        _options(
            tmp_path,
            core,
            experience,
            wheel,
            digest,
            dry_run=True,
        )
    )

    assert report.status == "dry_run"
    assert not core.exists()
    assert not experience.exists()
    assert not list((tmp_path / "backups").glob("*.zip"))


def test_upgrade_initializes_missing_databases_safely(tmp_path):
    core = tmp_path / "new" / "core.sqlite3"
    experience = tmp_path / "new" / "experience.sqlite3"
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")

    report = run_upgrade(_options(tmp_path, core, experience, wheel, digest))

    assert report.status == "complete"
    assert database_inventory(core)["tables"]["memories"]["rows"] == 0
    assert database_inventory(experience)["tables"]["experience_records"]["rows"] == 0


def test_cli_upgrade_returns_machine_readable_complete_report(
    tmp_path,
    monkeypatch,
    capsys,
):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    real_run_upgrade = upgrade.run_upgrade

    def run_with_source_health(options):
        return real_run_upgrade(
            UpgradeOptions(
                **{
                    **options.__dict__,
                    "health_command": [
                        sys.executable,
                        "-c",
                        "print('upgrade-health-ok')",
                    ],
                }
            )
        )

    monkeypatch.setattr(cli, "run_upgrade", run_with_source_health)
    result = cli.main(
        [
            "--db",
            str(core),
            "upgrade",
            "--mode",
            "python",
            "--experience-db",
            str(experience),
            "--artifact",
            str(wheel),
            "--expected-sha256",
            digest,
            "--backup-dir",
            str(tmp_path / "cli-backups"),
            "--state-dir",
            str(tmp_path / "cli-state"),
            "--json",
        ]
    )
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert payload["parity"] is True


def test_auto_mode_detects_default_wavemind_compose_file(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  wavemind:\n    image: ${WAVEMIND_IMAGE:-old:image}\n",
        encoding="utf-8",
    )

    assert cli._compose_defines_service(compose, "wavemind") is True
    assert cli._compose_defines_service(compose, "other") is False


def test_external_python_process_holding_database_is_reported(tmp_path):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3,time; "
                f"c=sqlite3.connect({str(core)!r}); "
                "c.execute('SELECT COUNT(*) FROM memories').fetchone(); "
                "print('ready', flush=True); time.sleep(30)"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        time.sleep(0.1)
        with pytest.raises(UpgradeError, match="open in another process"):
            run_upgrade(_options(tmp_path, core, experience, wheel, digest))
    finally:
        holder.terminate()
        try:
            holder.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.communicate(timeout=5)


def test_live_upgrade_lock_rejects_second_operator(tmp_path):
    lock = tmp_path / "upgrade.lock"
    with upgrade_lock(lock):
        with pytest.raises(UpgradeBlocked, match="another WaveMind upgrade"):
            with upgrade_lock(lock):
                pytest.fail("second operator acquired the live lock")


def test_downgrade_requires_explicit_opt_in(tmp_path, monkeypatch):
    core, experience, _memory_id, _experience_id = _state(tmp_path)
    wheel, digest = _wheel(tmp_path / "wavemind-2.11.0-py3-none-any.whl", "2.11.0")
    monkeypatch.setattr(upgrade, "_installed_version", lambda: "2.12.1")

    with pytest.raises(UpgradeBlocked, match="refusing downgrade"):
        run_upgrade(_options(tmp_path, core, experience, wheel, digest))
