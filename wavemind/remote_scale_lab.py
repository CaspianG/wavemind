from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


INVENTORY_SCHEMA = "wavemind.remote_qdrant_scale_lab.v1"
ATTESTATION_SCHEMA = "wavemind.remote_qdrant_scale_attestation.v1"
DEPLOYMENT_SCHEMA = "wavemind.remote_qdrant_scale_deployment.v1"
TUNNEL_SCHEMA = "wavemind.remote_qdrant_scale_tunnels.v1"
_SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_SAFE_SSH_HOST = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*$")
_PINNED_QDRANT_IMAGE = re.compile(
    r"^qdrant/qdrant(?::v\d+\.\d+\.\d+|@sha256:[0-9a-f]{64})$",
    re.IGNORECASE,
)


class RemoteScaleLabError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteQdrantShard:
    id: str
    ssh_host: str
    region: str
    zone: str
    provider: str
    qdrant_port: int = 6333

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RemoteQdrantShard":
        return cls(
            id=str(payload.get("id", "")).strip(),
            ssh_host=str(payload.get("ssh_host", "")).strip(),
            region=str(payload.get("region", "")).strip(),
            zone=str(payload.get("zone", "")).strip(),
            provider=str(payload.get("provider", "")).strip(),
            qdrant_port=int(payload.get("qdrant_port", 6333)),
        )


@dataclass(frozen=True)
class RemoteQdrantScaleInventory:
    deployment_id: str
    environment: str
    source: str
    image: str
    target_vectors: int
    vector_dim: int
    shards: tuple[RemoteQdrantShard, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RemoteQdrantScaleInventory":
        if payload.get("schema") != INVENTORY_SCHEMA:
            raise RemoteScaleLabError(f"inventory schema must be {INVENTORY_SCHEMA}")
        inventory = cls(
            deployment_id=str(payload.get("deployment_id", "")).strip(),
            environment=str(payload.get("environment", "")).strip(),
            source=str(payload.get("source", "")).strip(),
            image=str(payload.get("image", "")).strip(),
            target_vectors=int(payload.get("target_vectors", 100_000_000)),
            vector_dim=int(payload.get("vector_dim", 128)),
            shards=tuple(
                RemoteQdrantShard.from_dict(item)
                for item in payload.get("shards", [])
                if isinstance(item, Mapping)
            ),
        )
        inventory.validate()
        return inventory

    def validate(self) -> None:
        if not _SAFE_ID.fullmatch(self.deployment_id):
            raise RemoteScaleLabError("deployment_id must be a lowercase DNS-style identifier")
        if self.environment not in {"staging", "production"}:
            raise RemoteScaleLabError("environment must be staging or production")
        if self.source.lower() in {"", "local", "loopback", "fixture", "sample"}:
            raise RemoteScaleLabError("source must identify real remote infrastructure")
        if not _PINNED_QDRANT_IMAGE.fullmatch(self.image):
            raise RemoteScaleLabError("image must pin an exact Qdrant semver or sha256 digest")
        if self.target_vectors < 100_000_000:
            raise RemoteScaleLabError("target_vectors must be at least 100000000")
        if self.vector_dim < 1:
            raise RemoteScaleLabError("vector_dim must be positive")
        if len(self.shards) < 8:
            raise RemoteScaleLabError("100M remote scale lab requires at least eight shard hosts")

        values = {
            "id": [row.id for row in self.shards],
            "ssh_host": [row.ssh_host for row in self.shards],
            "zone": [row.zone for row in self.shards],
        }
        for field, rows in values.items():
            if any(not value for value in rows):
                raise RemoteScaleLabError(f"every shard requires {field}")
            if len(rows) != len(set(rows)):
                raise RemoteScaleLabError(f"shards must have unique {field} values")
        if len({row.region for row in self.shards if row.region}) < 3:
            raise RemoteScaleLabError("100M remote scale lab requires at least three regions")
        for row in self.shards:
            if not _SAFE_ID.fullmatch(row.id):
                raise RemoteScaleLabError(f"invalid shard id: {row.id}")
            if not _SAFE_SSH_HOST.fullmatch(row.ssh_host):
                raise RemoteScaleLabError(f"invalid SSH host for {row.id}")
            if not row.region or not row.provider:
                raise RemoteScaleLabError(f"shard {row.id} requires region and provider")
            if row.provider.lower() in {"local", "loopback"}:
                raise RemoteScaleLabError(f"shard {row.id} requires a remote provider")
            if not 1024 <= row.qdrant_port <= 65535:
                raise RemoteScaleLabError(f"invalid Qdrant port for {row.id}")

    @property
    def estimated_application_storage_gb(self) -> float:
        vector_gb = self.target_vectors * self.vector_dim * 4 / 1024**3
        payload_gb = self.target_vectors * 2.0 / 1024**2
        return round(vector_gb + payload_gb, 3)

    def required_disk_per_shard_gb(self, safety_factor: float = 1.15) -> int:
        return math.ceil(
            self.estimated_application_storage_gb * float(safety_factor) / len(self.shards)
        )


def load_remote_scale_inventory(path: str | Path) -> RemoteQdrantScaleInventory:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RemoteScaleLabError("inventory root must be a JSON object")
    return RemoteQdrantScaleInventory.from_dict(payload)


SSHRunner = Callable[[str, str], subprocess.CompletedProcess[str]]
CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_ssh_runner(ssh_host: str, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh_host, command],
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=900,
        check=False,
    )


def _default_command_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
        check=False,
    )


_ATTEST_COMMAND = r"""set -eu
machine_id=$(cat /etc/machine-id)
host_name=$(hostname)
cpu_count=$(getconf _NPROCESSORS_ONLN)
memory_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
disk_kb=$(df -Pk "$HOME" | awk 'NR == 2 {print $4}')
docker_version=$(docker version --format '{{.Server.Version}}')
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$machine_id" "$host_name" "$cpu_count" "$memory_kb" "$disk_kb" "$docker_version"
"""


def _redact(value: str) -> str:
    compact = " ".join(str(value).strip().split())[:500]
    compact = re.sub(r"(?i)(password|token|secret|api[-_ ]?key)=?\S*", r"\1=REDACTED", compact)
    return re.sub(r"(?i)bearer\s+\S+", "Bearer REDACTED", compact)


def _source_ref() -> str | None:
    configured = str(os.environ.get("GITHUB_SHA") or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", configured):
        return configured.lower()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value) else None


def _run_provenance() -> dict[str, Any]:
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip() or None
    repository = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    server_url = str(os.environ.get("GITHUB_SERVER_URL") or "").strip()
    run_url = (
        f"{server_url.rstrip('/')}/{repository}/actions/runs/{run_id}"
        if run_id and repository and server_url
        else None
    )
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_ref": _source_ref(),
        "execution_id": run_id or f"local-{int(time.time())}",
        "workflow_run_id": run_id,
        "workflow_run_url": run_url,
    }


def attest_remote_qdrant_scale_inventory(
    inventory: RemoteQdrantScaleInventory,
    *,
    runner: SSHRunner = _default_ssh_runner,
    min_cpu: int = 2,
    min_memory_gb: float = 16.0,
    min_disk_free_gb: float | None = None,
) -> dict[str, Any]:
    required_disk = float(
        min_disk_free_gb
        if min_disk_free_gb is not None
        else inventory.required_disk_per_shard_gb()
    )
    rows: list[dict[str, Any]] = []
    for shard in inventory.shards:
        completed = runner(shard.ssh_host, _ATTEST_COMMAND)
        row: dict[str, Any] = {
            "id": shard.id,
            "ssh_host": shard.ssh_host,
            "region": shard.region,
            "zone": shard.zone,
            "provider": shard.provider,
            "reachable": completed.returncode == 0,
            "issues": [],
        }
        if completed.returncode != 0:
            row["issues"].append("ssh_attestation_failed")
            row["error"] = _redact(completed.stderr or completed.stdout)
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
        if row["disk_free_gb"] < required_disk:
            row["issues"].append("insufficient_disk")
        if not docker_version:
            row["issues"].append("docker_unavailable")
        rows.append(row)

    identities = [row.get("machine_identity_sha256") for row in rows if row.get("reachable")]
    duplicates = {value for value in identities if identities.count(value) > 1}
    if duplicates:
        for row in rows:
            if row.get("machine_identity_sha256") in duplicates:
                row["issues"].append("duplicate_machine_identity")
    total_disk = round(sum(float(row.get("disk_free_gb") or 0.0) for row in rows), 3)
    required_total = round(required_disk * len(inventory.shards), 3)
    if total_disk < required_total:
        for row in rows:
            row["issues"].append("insufficient_aggregate_disk")
    status = "pass" if all(row["reachable"] and not row["issues"] for row in rows) else "fail"
    return {
        "schema": ATTESTATION_SCHEMA,
        **_run_provenance(),
        "status": status,
        "deployment_id": inventory.deployment_id,
        "environment": inventory.environment,
        "source": inventory.source,
        "target_vectors": inventory.target_vectors,
        "vector_dim": inventory.vector_dim,
        "thresholds": {
            "min_shards": 8,
            "min_regions": 3,
            "min_cpu": min_cpu,
            "min_memory_gb": min_memory_gb,
            "min_disk_free_gb_per_shard": required_disk,
            "required_total_disk_gb": required_total,
            "unique_machine_identity_required": True,
        },
        "summary": {
            "shard_count": len(rows),
            "region_count": len({row["region"] for row in rows}),
            "reachable_count": sum(bool(row["reachable"]) for row in rows),
            "ready_count": sum(not row["issues"] for row in rows),
            "unique_machine_count": len(set(identities)),
            "total_disk_free_gb": total_disk,
        },
        "shards": rows,
        "claim_boundary": (
            "Remote capacity and machine-identity attestation only. The 100M claim remains "
            "locked until the measured benchmark artifact passes strict evidence validation."
        ),
    }


def validate_remote_qdrant_scale_attestation(
    payload: Mapping[str, Any] | None,
    *,
    min_shards: int = 8,
    min_regions: int = 3,
    min_target_vectors: int = 100_000_000,
    min_memory_gb: float = 16.0,
    min_disk_per_shard_gb: float = 35.0,
) -> dict[str, Any]:
    if not payload:
        return {
            "status": "action_required",
            "issues": ["missing remote Qdrant 100M attestation artifact"],
            "evidence": "no remote eight-host Qdrant capacity attestation",
        }
    issues: list[str] = []

    def require(condition: bool, issue: str) -> None:
        if not condition:
            issues.append(issue)

    environment = str(payload.get("environment") or "").lower()
    source = str(payload.get("source") or "").lower()
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), Mapping) else {}
    shards = [row for row in payload.get("shards", []) if isinstance(row, Mapping)]
    shard_count = int(summary.get("shard_count") or len(shards))
    hashes = [str(row.get("machine_identity_sha256") or "") for row in shards]
    source_ref = str(payload.get("source_ref") or "")
    execution_id = str(payload.get("execution_id") or "")

    require(payload.get("schema") == ATTESTATION_SCHEMA, "invalid remote scale attestation schema")
    require(payload.get("status") == "pass", "remote scale attestation status must be pass")
    require(bool(payload.get("generated_at")), "generated_at is required")
    require(bool(re.fullmatch(r"[0-9a-fA-F]{40}", source_ref)), "source_ref must be a full Git commit SHA")
    require(bool(execution_id), "execution_id is required")
    require(environment in {"staging", "production"}, "environment must be staging/production")
    require(source not in {"", "local", "loopback", "fixture", "sample"}, "source must be remote")
    require(int(payload.get("target_vectors") or 0) >= min_target_vectors, f"target_vectors must be >= {min_target_vectors}")
    require(shard_count >= min_shards, f"shard_count must be >= {min_shards}")
    require(int(summary.get("region_count") or 0) >= min_regions, f"region_count must be >= {min_regions}")
    require(int(summary.get("ready_count") or 0) == shard_count, "every shard must be ready")
    require(int(summary.get("reachable_count") or 0) == shard_count, "every shard must be reachable")
    require(int(summary.get("unique_machine_count") or 0) == shard_count, "every shard needs a unique machine identity")
    require(bool(thresholds.get("unique_machine_identity_required")), "unique machine identity policy is required")
    require(float(thresholds.get("min_memory_gb") or 0.0) >= min_memory_gb, f"min_memory_gb must be >= {min_memory_gb:g}")
    require(
        float(thresholds.get("min_disk_free_gb_per_shard") or 0.0) >= min_disk_per_shard_gb,
        f"min_disk_free_gb_per_shard must be >= {min_disk_per_shard_gb:g}",
    )
    require(len(shards) == shard_count, "attestation must contain every shard row")
    require(all(bool(value) for value in hashes), "every shard needs a hashed machine identity")
    require(len(set(hashes)) == shard_count, "machine identity hashes must be unique")
    require(
        all(bool(row.get("reachable")) and not list(row.get("issues") or []) for row in shards),
        "every shard row must be reachable and issue-free",
    )
    evidence = (
        f"remote shards {shard_count}, regions {summary.get('region_count')}, "
        f"unique machines {summary.get('unique_machine_count')}, target "
        f"{payload.get('target_vectors')}, RAM floor {thresholds.get('min_memory_gb')} GB, "
        f"disk floor {thresholds.get('min_disk_free_gb_per_shard')} GB/shard"
    )
    return {
        "status": "pass" if not issues else "fail",
        "issues": list(dict.fromkeys(issues)),
        "evidence": evidence if not issues else f"{evidence}; issues: {', '.join(dict.fromkeys(issues))}",
    }


def render_qdrant_env(
    inventory: RemoteQdrantScaleInventory,
    shard: RemoteQdrantShard,
    *,
    api_key: str,
) -> str:
    if not api_key:
        raise RemoteScaleLabError("remote Qdrant deployment requires an API key")
    values = {
        "COMPOSE_PROJECT_NAME": f"wavemind-scale-{inventory.deployment_id}-{shard.id}",
        "QDRANT_IMAGE": inventory.image,
        "QDRANT_PORT": str(shard.qdrant_port),
        "QDRANT_API_KEY": api_key,
    }
    return "".join(f"{key}={_dotenv_quote(str(value))}\n" for key, value in values.items())


def _dotenv_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return f'"{escaped}"'


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
            timeout=1800,
            check=False,
        )
    return runner(ssh_host, command if stdin is None else f"{command}\n<STDIN:{len(stdin)}>")


def deploy_remote_qdrant_scale_inventory(
    inventory: RemoteQdrantScaleInventory,
    *,
    compose_text: str,
    api_key: str,
    runner: SSHRunner = _default_ssh_runner,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for shard in inventory.shards:
        remote_dir = f"$HOME/.local/share/wavemind-scale/{inventory.deployment_id}/{shard.id}"
        env_text = render_qdrant_env(inventory, shard, api_key=api_key)
        steps = (
            (f"umask 077; mkdir -p {remote_dir}; cat > {remote_dir}/docker-compose.yml", compose_text),
            (f"umask 077; cat > {remote_dir}/.env", env_text),
            (
                f"set -eu; cd {remote_dir}; docker compose config --quiet; "
                "docker compose pull; docker compose up -d --wait --remove-orphans",
                None,
            ),
            (
                f"set -eu; cd {remote_dir}; docker compose ps --format json >/dev/null; "
                f"curl -fsS http://127.0.0.1:{shard.qdrant_port}/healthz >/dev/null",
                None,
            ),
        )
        ok = True
        error = None
        for command, stdin in steps:
            completed = _run_ssh_with_input(shard.ssh_host, command, stdin, runner)
            if completed.returncode != 0:
                ok = False
                error = _redact(completed.stderr or completed.stdout)
                break
        rows.append({"id": shard.id, "ssh_host": shard.ssh_host, "deployed": ok, "error": error})
    return {
        "schema": DEPLOYMENT_SCHEMA,
        "status": "pass" if all(row["deployed"] for row in rows) else "fail",
        "deployment_id": inventory.deployment_id,
        "environment": inventory.environment,
        "source": inventory.source,
        "image": inventory.image,
        "target_vectors": inventory.target_vectors,
        "shards": rows,
        "claim_boundary": "Deployment and loopback health only; measured 100M evidence is still required.",
    }


def open_remote_qdrant_tunnels(
    inventory: RemoteQdrantScaleInventory,
    *,
    api_key: str,
    local_port_base: int = 16_333,
    control_dir: str | Path | None = None,
    runner: CommandRunner = _default_command_runner,
    probe_timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    if not api_key:
        raise RemoteScaleLabError("remote Qdrant tunnels require an API key")
    if local_port_base < 1024 or local_port_base + len(inventory.shards) > 65535:
        raise RemoteScaleLabError("local tunnel port range is invalid")
    control_root = Path(
        control_dir
        if control_dir is not None
        else Path(os.environ.get("RUNNER_TEMP") or "state/remote-scale") / "wavemind-ssh"
    )
    control_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index, shard in enumerate(inventory.shards):
        local_port = local_port_base + index
        control_socket = _control_socket(control_root, inventory, shard)
        command = [
            "ssh",
            "-fN",
            "-M",
            "-S",
            str(control_socket),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-L",
            f"{local_port}:127.0.0.1:{shard.qdrant_port}",
            shard.ssh_host,
        ]
        completed = runner(command)
        url = f"http://127.0.0.1:{local_port}"
        error = None if completed.returncode == 0 else _redact(completed.stderr or completed.stdout)
        healthy = False
        if completed.returncode == 0:
            deadline = time.monotonic() + max(1.0, probe_timeout_seconds)
            while time.monotonic() < deadline:
                request = urllib.request.Request(url + "/collections", headers={"api-key": api_key})
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        healthy = 200 <= int(response.status) < 300
                    if healthy:
                        break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.5)
            if not healthy:
                error = "Qdrant did not become healthy through the pinned SSH tunnel"
        rows.append(
            {
                "id": shard.id,
                "ssh_host": shard.ssh_host,
                "local_url": url,
                "local_port": local_port,
                "remote_port": shard.qdrant_port,
                "control_socket": str(control_socket),
                "tunnel_started": completed.returncode == 0,
                "healthy": healthy,
                "error": error,
            }
        )
    return {
        "schema": TUNNEL_SCHEMA,
        "status": "pass" if all(row["tunnel_started"] and row["healthy"] for row in rows) else "fail",
        "deployment_id": inventory.deployment_id,
        "source": inventory.source,
        "shard_count": len(rows),
        "urls": [row["local_url"] for row in rows],
        "shards": rows,
        "security": {
            "qdrant_publicly_exposed": False,
            "strict_host_key_checking": True,
            "api_key_serialized": False,
        },
        "claim_boundary": "Transport readiness only; tunnel health is not 100M benchmark evidence.",
    }


def close_remote_qdrant_tunnels(
    inventory: RemoteQdrantScaleInventory,
    *,
    control_dir: str | Path | None = None,
    runner: CommandRunner = _default_command_runner,
) -> dict[str, Any]:
    control_root = Path(
        control_dir
        if control_dir is not None
        else Path(os.environ.get("RUNNER_TEMP") or "state/remote-scale") / "wavemind-ssh"
    )
    rows: list[dict[str, Any]] = []
    for shard in inventory.shards:
        control_socket = _control_socket(control_root, inventory, shard)
        if not control_socket.exists():
            rows.append({"id": shard.id, "closed": True, "already_absent": True})
            continue
        completed = runner(
            ["ssh", "-S", str(control_socket), "-O", "exit", shard.ssh_host]
        )
        closed = completed.returncode == 0
        rows.append(
            {
                "id": shard.id,
                "closed": closed,
                "already_absent": False,
                "error": None if closed else _redact(completed.stderr or completed.stdout),
            }
        )
    return {
        "schema": "wavemind.remote_qdrant_scale_tunnel_cleanup.v1",
        "status": "pass" if all(row["closed"] for row in rows) else "fail",
        "deployment_id": inventory.deployment_id,
        "shards": rows,
    }


def _control_socket(
    control_root: Path,
    inventory: RemoteQdrantScaleInventory,
    shard: RemoteQdrantShard,
) -> Path:
    digest = hashlib.sha256(
        f"{inventory.deployment_id}:{shard.id}:{shard.ssh_host}".encode()
    ).hexdigest()[:20]
    return control_root / f"wm-{digest}.sock"
