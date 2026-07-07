import json

from wavemind import build_postgres_pitr_plan
import wavemind.cli as cli


ENV_NAMES = (
    "WAVEMIND_POSTGRES_DSN",
    "WAVEMIND_POSTGRES_BASEBACKUP_DIR",
    "WAVEMIND_POSTGRES_WAL_ARCHIVE_DIR",
    "WAVEMIND_POSTGRES_RESTORE_DATA_DIR",
    "WAVEMIND_POSTGRES_RESTORE_TARGET_TIME",
)


def test_postgres_pitr_plan_is_secret_safe_and_structurally_ready(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.setenv(name, f"secret-value-for-{name.lower()}")

    plan = build_postgres_pitr_plan(generated_at="2026-07-07T00:00:00Z")
    payload = plan.as_dict()

    assert payload["schema"] == "wavemind.postgres_pitr_plan.v1"
    assert payload["status"] == "ready"
    assert payload["environment_status"] == "ready"
    assert payload["missing_env"] == []
    assert payload["retention_hours"] == 72
    assert payload["validation"]["ok"] is True
    checks = payload["validation"]["checks"]
    assert checks["has_wal_archiving_command"] is True
    assert checks["has_base_backup_command"] is True
    assert checks["has_restore_command"] is True
    assert checks["has_recovery_signal"] is True
    assert checks["has_restore_target_time"] is True
    assert checks["has_replay_verification"] is True
    assert checks["has_promotion_command"] is True
    assert checks["secret_values_not_embedded"] is True

    serialized = json.dumps(payload)
    for name in ENV_NAMES:
        assert name in serialized
        assert f"secret-value-for-{name.lower()}" not in serialized


def test_postgres_pitr_plan_reports_missing_env_without_failing_structure(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    plan = build_postgres_pitr_plan(generated_at="2026-07-07T00:00:00Z")
    payload = plan.as_dict()

    assert payload["status"] == "ready"
    assert payload["environment_status"] == "missing_env"
    assert payload["missing_env"] == list(ENV_NAMES)
    assert "not an executed drill" in payload["validation"]["warnings"][0]


def test_postgres_pitr_cli_outputs_json_and_can_fail_on_missing_env(monkeypatch, capsys):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    code = cli.main(["postgres-pitr-plan", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "wavemind.postgres_pitr_plan.v1"
    assert payload["environment_status"] == "missing_env"

    code = cli.main(["postgres-pitr-plan", "--fail-on-missing-env", "--json"])
    assert code == 4
