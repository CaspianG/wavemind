from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, urlparse

from .active_active_drill import run_active_active_drill
from .sharding import HTTPNamespaceShardClient


INVENTORY_SCHEMA = "wavemind.remote_production_lab.v1"
ATTESTATION_SCHEMA = "wavemind.remote_production_attestation.v1"
DEPLOYMENT_SCHEMA = "wavemind.remote_production_deployment.v1"
FAILURE_DRILL_SCHEMA = "wavemind.remote_region_failure_drill.v1"
_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SAFE_SSH_HOST = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*$")
_PINNED_IMAGE = re.compile(
    r"^ghcr\.io/[a-z0-9._-]+/[a-z0-9._-]+:(?:v?\d+\.\d+\.\d+|sha-[0-9a-f]{7,64})$",
    re.IGNORECASE,
)


class RemoteLabError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteRegion:
    id: str
    ssh_host: str
    public_url: str
    region: str
    zone: str
    provider: str
    http_port: int = 8000

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RemoteRegion":
        return cls(
            id=str(payload.get("id", "")).strip(),
            ssh_host=str(payload.get("ssh_host", "")).strip(),
            public_url=str(payload.get("public_url", "")).strip().rstrip("/"),
            region=str(payload.get("region", "")).strip(),
            zone=str(payload.get("zone", "")).strip(),
            provider=str(payload.get("provider", "")).strip(),
            http_port=int(payload.get("http_port", 8000)),
        )


@dataclass(frozen=True)
class RemoteLabInventory:
    deployment_id: str
    environment: str
    source: str
    image: str
    regions: tuple[RemoteRegion, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RemoteLabInventory":
        if payload.get("schema") != INVENTORY_SCHEMA:
            raise RemoteLabError(f"inventory schema must be {INVENTORY_SCHEMA}")
        inventory = cls(
            deployment_id=str(payload.get("deployment_id", "")).strip(),
            environment=str(payload.get("environment", "")).strip(),
            source=str(payload.get("source", "")).strip(),
            image=str(payload.get("image", "")).strip(),
            regions=tuple(
                RemoteRegion.from_dict(item)
                for item in payload.get("regions", [])
                if isinstance(item, Mapping)
            ),
        )
        inventory.validate()
        return inventory

    def validate(self) -> None:
        if not _SAFE_ID.fullmatch(self.deployment_id):
            raise RemoteLabError("deployment_id must be a lowercase DNS-style identifier")
        if self.environment not in {"staging", "production"}:
            raise RemoteLabError("environment must be staging or production")
        if self.source in {"", "local", "loopback", "fixture", "sample"}:
            raise RemoteLabError("source must identify a real remote deployment")
        if not _PINNED_IMAGE.fullmatch(self.image):
            raise RemoteLabError("image must use an immutable ghcr.io release or sha tag")
        if len(self.regions) < 3:
            raise RemoteLabError("remote production lab requires at least three regions")

        for field, values in {
            "id": [row.id for row in self.regions],
            "ssh_host": [row.ssh_host for row in self.regions],
            "public_url": [row.public_url for row in self.regions],
            "region": [row.region for row in self.regions],
            "zone": [row.zone for row in self.regions],
        }.items():
            if any(not value for value in values):
                raise RemoteLabError(f"every region requires {field}")
            if len(set(values)) != len(values):
                raise RemoteLabError(f"remote regions must have unique {field} values")

        for row in self.regions:
            if not _SAFE_ID.fullmatch(row.id):
                raise RemoteLabError(f"invalid region id: {row.id}")
            if not _SAFE_SSH_HOST.fullmatch(row.ssh_host):
                raise RemoteLabError(f"invalid SSH host for {row.id}")
            if not row.provider or row.provider.lower() in {"local", "loopback"}:
                raise RemoteLabError(f"region {row.id} requires a remote provider")
            if not 1 <= row.http_port <= 65535:
                raise RemoteLabError(f"invalid HTTP port for {row.id}")
            _validate_public_url(row.public_url, row.id)

    def active_active_manifest(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "environment": self.environment,
            "source": self.source,
            "regions": [
                {
                    "id": row.id,
                    "url": row.public_url,
                    "region": row.region,
                    "zone": row.zone,
                    "provider": row.provider,
                }
                for row in self.regions
            ],
        }


def load_remote_inventory(path: str | Path) -> RemoteLabInventory:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RemoteLabError("inventory root must be a JSON object")
    return RemoteLabInventory.from_dict(payload)


def _validate_public_url(value: str, region_id: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RemoteLabError(f"region {region_id} public_url must be HTTP(S)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RemoteLabError(f"region {region_id} public_url must not contain credentials/query/fragment")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise RemoteLabError(f"region {region_id} public_url must not be loopback")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if address.is_loopback or address.is_unspecified or address.is_link_local:
        raise RemoteLabError(f"region {region_id} public_url must not be loopback/link-local")


_ATTEST_COMMAND = r"""set -eu
machine_id=$(cat /etc/machine-id)
host_name=$(hostname)
cpu_count=$(getconf _NPROCESSORS_ONLN)
memory_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
disk_kb=$(df -Pk "$HOME" | awk 'NR == 2 {print $4}')
docker_version=$(docker version --format '{{.Server.Version}}')
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$machine_id" "$host_name" "$cpu_count" "$memory_kb" "$disk_kb" "$docker_version"
"""


SSHRunner = Callable[[str, str], subprocess.CompletedProcess[str]]


def _default_ssh_runner(ssh_host: str, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            ssh_host,
            command,
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=45,
        check=False,
    )


def attest_remote_inventory(
    inventory: RemoteLabInventory,
    *,
    runner: SSHRunner = _default_ssh_runner,
    min_cpu: int = 2,
    min_memory_gb: float = 2.0,
    min_disk_free_gb: float = 10.0,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for region in inventory.regions:
        completed = runner(region.ssh_host, _ATTEST_COMMAND)
        row: dict[str, Any] = {
            "id": region.id,
            "ssh_host": region.ssh_host,
            "public_url": region.public_url,
            "region": region.region,
            "zone": region.zone,
            "provider": region.provider,
            "reachable": completed.returncode == 0,
            "issues": [],
        }
        if completed.returncode != 0:
            row["issues"].append("ssh_attestation_failed")
            row["error"] = _redact_error(completed.stderr or completed.stdout)
            rows.append(row)
            continue
        fields = completed.stdout.strip().split("\t")
        if len(fields) != 6:
            row["reachable"] = False
            row["issues"].append("invalid_attestation_output")
            rows.append(row)
            continue
        machine_id, hostname, cpu, memory_kb, disk_kb, docker_version = fields
        row.update(
            {
                "hostname": hostname,
                "machine_identity_sha256": hashlib.sha256(machine_id.encode()).hexdigest(),
                "cpu_count": int(cpu),
                "memory_gb": round(int(memory_kb) / 1024 / 1024, 3),
                "disk_free_gb": round(int(disk_kb) / 1024 / 1024, 3),
                "docker_version": docker_version,
            }
        )
        if row["cpu_count"] < min_cpu:
            row["issues"].append("insufficient_cpu")
        if row["memory_gb"] < min_memory_gb:
            row["issues"].append("insufficient_memory")
        if row["disk_free_gb"] < min_disk_free_gb:
            row["issues"].append("insufficient_disk")
        if not docker_version:
            row["issues"].append("docker_unavailable")
        rows.append(row)

    identities = [row.get("machine_identity_sha256") for row in rows if row.get("reachable")]
    duplicate_identities = len(identities) != len(set(identities))
    if duplicate_identities:
        for row in rows:
            if row.get("reachable"):
                row["issues"].append("duplicate_machine_identity")

    status = "pass" if len(rows) >= 3 and all(not row["issues"] for row in rows) else "fail"
    return {
        "schema": ATTESTATION_SCHEMA,
        "status": status,
        "deployment_id": inventory.deployment_id,
        "environment": inventory.environment,
        "source": inventory.source,
        "thresholds": {
            "min_regions": 3,
            "min_cpu": min_cpu,
            "min_memory_gb": min_memory_gb,
            "min_disk_free_gb": min_disk_free_gb,
            "unique_machine_identity_required": True,
        },
        "summary": {
            "region_count": len(rows),
            "reachable_count": sum(bool(row["reachable"]) for row in rows),
            "ready_count": sum(not row["issues"] for row in rows),
            "unique_machine_count": len(set(identities)),
        },
        "regions": rows,
        "claim_boundary": (
            "SSH host and machine-identity attestation only. Active-active, failure recovery, "
            "serverless, and load claims require their dedicated measured artifacts."
        ),
    }


def _redact_error(value: str) -> str:
    compact = " ".join(value.strip().split())[:500]
    compact = re.sub(r"(?i)(password|token|secret|api[-_ ]?key)=?\S*", r"\1=REDACTED", compact)
    compact = re.sub(r"(?i)bearer\s+\S+", "Bearer REDACTED", compact)
    return compact


def render_region_env(
    inventory: RemoteLabInventory,
    region: RemoteRegion,
    *,
    api_key: str,
    postgres_password: str,
) -> str:
    if not api_key or not postgres_password:
        raise RemoteLabError("remote deployment requires API and PostgreSQL secrets")
    values = {
        "COMPOSE_PROJECT_NAME": f"wavemind-{inventory.deployment_id}-{region.id}",
        "WAVEMIND_IMAGE": inventory.image,
        "WAVEMIND_REGION_ID": region.id,
        "WAVEMIND_HTTP_PORT": str(region.http_port),
        "WAVEMIND_API_KEY": api_key,
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_PASSWORD_URLENCODED": quote(postgres_password, safe=""),
    }
    return "".join(f"{key}={_dotenv_quote(value)}\n" for key, value in values.items())


def _dotenv_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return f'"{escaped}"'


def deploy_remote_inventory(
    inventory: RemoteLabInventory,
    *,
    compose_text: str,
    api_key: str,
    postgres_password: str,
    runner: SSHRunner = _default_ssh_runner,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for region in inventory.regions:
        remote_dir = f"$HOME/.local/share/wavemind/{inventory.deployment_id}/{region.id}"
        env_text = render_region_env(
            inventory,
            region,
            api_key=api_key,
            postgres_password=postgres_password,
        )
        steps = (
            (f"umask 077; mkdir -p {remote_dir}; cat > {remote_dir}/docker-compose.yml", compose_text),
            (f"umask 077; cat > {remote_dir}/.env", env_text),
            (
                f"cd {remote_dir}; docker compose config --quiet; "
                "docker compose pull; docker compose up -d --wait --remove-orphans",
                None,
            ),
            (
                f"cd {remote_dir}; docker compose ps --format json; "
                f"python3 -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{region.http_port}/healthz', timeout=10).read()\"",
                None,
            ),
        )
        ok = True
        error = ""
        for command, stdin in steps:
            completed = _run_ssh_with_input(region.ssh_host, command, stdin, runner)
            if completed.returncode != 0:
                ok = False
                error = _redact_error(completed.stderr or completed.stdout)
                break
        rows.append(
            {
                "id": region.id,
                "ssh_host": region.ssh_host,
                "public_url": region.public_url,
                "deployed": ok,
                "error": error or None,
            }
        )
    return {
        "schema": DEPLOYMENT_SCHEMA,
        "status": "pass" if all(row["deployed"] for row in rows) else "fail",
        "deployment_id": inventory.deployment_id,
        "environment": inventory.environment,
        "image": inventory.image,
        "regions": rows,
        "active_active_manifest": inventory.active_active_manifest(),
        "claim_boundary": (
            "Deployment and per-host loopback health only. Strict active-active admission "
            "requires the external benchmark and failure drill artifacts."
        ),
    }


def _run_ssh_with_input(
    ssh_host: str,
    command: str,
    stdin: str | None,
    runner: SSHRunner,
) -> subprocess.CompletedProcess[str]:
    if runner is _default_ssh_runner:
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh_host, command],
            input=stdin,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=900,
            check=False,
        )
    return runner(ssh_host, command if stdin is None else f"{command}\n<STDIN:{len(stdin)}>")


def probe_public_regions(
    inventory: RemoteLabInventory,
    *,
    api_key: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for region in inventory.regions:
        request = urllib.request.Request(region.public_url + "/healthz")
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status_code = int(response.status)
            error = None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            status_code = 0
            error = _redact_error(str(exc))
        rows.append(
            {
                "id": region.id,
                "public_url": region.public_url,
                "status_code": status_code,
                "healthy": 200 <= status_code < 300,
                "error": error,
            }
        )
    return {
        "status": "pass" if all(row["healthy"] for row in rows) else "fail",
        "regions": rows,
    }


def run_remote_region_failure_drill(
    inventory: RemoteLabInventory,
    *,
    failed_region: str,
    api_key: str,
    namespace_prefix: str = "remote-region-failure",
    namespace_count: int = 16,
    runner: SSHRunner = _default_ssh_runner,
    client: Any | None = None,
    recovery_timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    by_id = {row.id: row for row in inventory.regions}
    if failed_region not in by_id:
        raise RemoteLabError(f"unknown failed region: {failed_region}")
    if not api_key:
        raise RemoteLabError("remote failure drill requires WAVEMIND_REMOTE_API_KEY")
    if namespace_count <= 0:
        raise RemoteLabError("namespace_count must be positive")

    regions = {row.id: row.public_url for row in inventory.regions}
    client = client or HTTPNamespaceShardClient(
        api_key=api_key,
        timeout=15.0,
        trust_env=False,
    )
    victim = by_id[failed_region]
    remote_dir = f"$HOME/.local/share/wavemind/{inventory.deployment_id}/{victim.id}"
    common = {
        "namespace_prefix": namespace_prefix,
        "namespace_count": namespace_count,
        "min_convergence_rate": 1.0,
    }
    seed = run_active_active_drill(regions, client=client, mode="seed", **common)
    if seed.get("status") != "pass":
        return {
            "schema": FAILURE_DRILL_SCHEMA,
            "status": "fail",
            "deployment_id": inventory.deployment_id,
            "environment": inventory.environment,
            "source": inventory.source,
            "failed_region": failed_region,
            "region_count": len(regions),
            "namespace_prefix": namespace_prefix,
            "namespace_count": namespace_count,
            "physical_failure": {
                "stop": {"ok": False, "error": "not attempted because seed phase failed"},
                "start": {"ok": False, "error": "not required because stop was not attempted"},
                "failure_observed": False,
                "health_recovered": False,
            },
            "phase_statuses": {"seed": "fail", "outage": "not_run", "recover": "not_run"},
            "seed": seed,
            "outage": {"status": "not_run"},
            "recover": {"status": "not_run"},
            "claim_boundary": (
                "No region was stopped because the seed baseline failed. Physical outage "
                "evidence requires a healthy converged baseline first."
            ),
        }
    stop_result: dict[str, Any] = {"ok": False, "error": None}
    start_result: dict[str, Any] = {"ok": False, "error": None}
    outage: dict[str, Any] = {"status": "not_run"}
    recovery: dict[str, Any] = {"status": "not_run"}
    recovered_health = False

    try:
        stopped = runner(
            victim.ssh_host,
            f"set -eu; cd {remote_dir}; docker compose stop --timeout 30 api",
        )
        stop_result = {
            "ok": stopped.returncode == 0,
            "error": None if stopped.returncode == 0 else _redact_error(stopped.stderr or stopped.stdout),
        }
        if not stop_result["ok"]:
            raise RemoteLabError("failed to stop victim API container")
        outage = run_active_active_drill(
            regions,
            client=client,
            mode="outage",
            failed_region=failed_region,
            **common,
        )
    except Exception as exc:
        if outage.get("status") == "not_run":
            outage = {"status": "fail", "error": _redact_error(str(exc))}
    finally:
        started = runner(
            victim.ssh_host,
            f"set -eu; cd {remote_dir}; docker compose up -d --wait api",
        )
        start_result = {
            "ok": started.returncode == 0,
            "error": None if started.returncode == 0 else _redact_error(started.stderr or started.stdout),
        }

    if start_result["ok"]:
        deadline = time.monotonic() + max(1.0, recovery_timeout_seconds)
        while time.monotonic() < deadline:
            try:
                client.stats(victim.public_url)
                recovered_health = True
                break
            except Exception:
                time.sleep(1.0)
        if recovered_health:
            recovery = run_active_active_drill(
                regions,
                client=client,
                mode="recover",
                failed_region=failed_region,
                **common,
            )

    physical_failure_observed = (
        failed_region in set(outage.get("unavailable_regions") or [])
        and len(outage.get("surviving_regions") or []) >= 2
    )
    phase_statuses = {
        "seed": seed.get("status"),
        "outage": outage.get("status"),
        "recover": recovery.get("status"),
    }
    status = (
        "pass"
        if all(value == "pass" for value in phase_statuses.values())
        and stop_result["ok"]
        and start_result["ok"]
        and physical_failure_observed
        and recovered_health
        else "fail"
    )
    return {
        "schema": FAILURE_DRILL_SCHEMA,
        "status": status,
        "deployment_id": inventory.deployment_id,
        "environment": inventory.environment,
        "source": inventory.source,
        "failed_region": failed_region,
        "region_count": len(regions),
        "namespace_prefix": namespace_prefix,
        "namespace_count": namespace_count,
        "physical_failure": {
            "stop": stop_result,
            "start": start_result,
            "failure_observed": physical_failure_observed,
            "health_recovered": recovered_health,
        },
        "phase_statuses": phase_statuses,
        "seed": seed,
        "outage": outage,
        "recover": recovery,
        "claim_boundary": (
            "Physical API-container region outage and recovery evidence. Production admission "
            "also requires independent-host attestation and the external active-active SLO artifact."
        ),
    }


def validate_remote_region_failure_drill(
    payload: Mapping[str, Any] | None,
    *,
    min_regions: int = 3,
    min_namespaces: int = 16,
) -> dict[str, Any]:
    issues: list[str] = []
    if not payload:
        return {
            "status": "action_required",
            "issues": ["missing remote region failure drill artifact"],
            "evidence": "no remote physical region failure and recovery artifact",
        }

    def require(condition: bool, issue: str) -> None:
        if not condition:
            issues.append(issue)

    physical = payload.get("physical_failure") or {}
    phases = payload.get("phase_statuses") or {}
    outage = payload.get("outage") or {}
    recovery = payload.get("recover") or {}
    recovery_sync = recovery.get("sync") or {}
    recovery_verification = recovery.get("verification") or {}
    environment = str(payload.get("environment") or "").lower()
    source = str(payload.get("source") or "").lower()

    require(payload.get("schema") == FAILURE_DRILL_SCHEMA, "invalid failure drill schema")
    require(payload.get("status") == "pass", "failure drill status must be pass")
    require(environment in {"staging", "production"}, "environment must be staging/production")
    require(source not in {"", "local", "loopback", "fixture", "sample"}, "source must be remote")
    require(int(payload.get("region_count") or 0) >= min_regions, f"region_count must be >= {min_regions}")
    require(
        int(payload.get("namespace_count") or 0) >= min_namespaces,
        f"namespace_count must be >= {min_namespaces}",
    )
    require(bool(payload.get("failed_region")), "failed_region is required")
    require(bool((physical.get("stop") or {}).get("ok")), "physical stop must pass")
    require(bool((physical.get("start") or {}).get("ok")), "physical restart must pass")
    require(bool(physical.get("failure_observed")), "failed endpoint must be observed unavailable")
    require(bool(physical.get("health_recovered")), "failed endpoint health must recover")
    for phase in ("seed", "outage", "recover"):
        require(phases.get(phase) == "pass", f"{phase} phase must pass")
    require(
        payload.get("failed_region") in set(outage.get("unavailable_regions") or []),
        "outage must identify the selected failed region",
    )
    require(len(outage.get("surviving_regions") or []) >= 2, "at least two survivors are required")
    require(
        float(recovery_verification.get("convergence_rate") or 0.0) >= 1.0,
        "recovery convergence_rate must be 1.0",
    )
    require(
        float(recovery_verification.get("delete_suppression_rate") or 0.0) >= 1.0,
        "recovery delete_suppression_rate must be 1.0",
    )
    require(
        int(recovery_sync.get("final_noop_records_imported", -1)) == 0,
        "recovery final_noop_records_imported must be 0",
    )
    require(
        int(recovery_sync.get("final_noop_tombstones_imported", -1)) == 0,
        "recovery final_noop_tombstones_imported must be 0",
    )
    evidence = (
        f"regions {payload.get('region_count')}, failed {payload.get('failed_region')}, "
        f"namespaces {payload.get('namespace_count')}, physical stop/start "
        f"{bool((physical.get('stop') or {}).get('ok'))}/{bool((physical.get('start') or {}).get('ok'))}, "
        f"failure observed {bool(physical.get('failure_observed'))}, health recovered "
        f"{bool(physical.get('health_recovered'))}, recovery convergence "
        f"{recovery_verification.get('convergence_rate')}, delete suppression "
        f"{recovery_verification.get('delete_suppression_rate')}"
    )
    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "evidence": evidence if not issues else f"{evidence}; issues: {', '.join(issues)}",
    }
