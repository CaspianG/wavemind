from pathlib import Path
import re

import wavemind


CHART_ROOT = Path("deploy/helm/wavemind")


def read_chart_file(relative: str) -> str:
    return (CHART_ROOT / relative).read_text(encoding="utf-8")


def test_helm_chart_core_files_exist_and_track_app_version():
    assert (CHART_ROOT / "Chart.yaml").exists()
    assert (CHART_ROOT / "values.yaml").exists()
    assert (CHART_ROOT / "templates/statefulset.yaml").exists()
    assert (CHART_ROOT / "templates/repair-cronjob.yaml").exists()
    assert (CHART_ROOT / "templates/memory-os-cronjob.yaml").exists()
    assert (CHART_ROOT / "templates/hpa.yaml").exists()

    chart = read_chart_file("Chart.yaml")
    values = read_chart_file("values.yaml")

    assert "apiVersion: v2" in chart
    assert "name: wavemind" in chart
    assert f'appVersion: "{wavemind.__version__}"' in chart
    assert f'tag: "{wavemind.__version__}"' in values
    assert "repository: ghcr.io/caspiang/wavemind" in values
    assert "replicaCount: 3" in values
    assert "replicationFactor: 2" in values
    assert "recoveryJournal: /data/wavemind.recovery.jsonl" in values
    assert "autoscaling:" in values
    assert "maxReplicas: 12" in values
    assert "memoryOs:" in values
    assert "strictPlan: true" in values
    assert "productionAdmission:" in values
    assert "evidenceRoot: /evidence" in values
    assert "backends:" in values
    assert "store: sqlite" in values


def test_helm_chart_templates_define_cluster_network_and_state():
    helpers = read_chart_file("templates/_helpers.tpl")
    statefulset = read_chart_file("templates/statefulset.yaml")
    service = read_chart_file("templates/service.yaml")
    headless = read_chart_file("templates/service-headless.yaml")

    assert 'define "wavemind.fullname"' in helpers
    assert 'define "wavemind.headlessServiceName"' in helpers
    assert "kind: StatefulSet" in statefulset
    assert "serviceName: {{ include \"wavemind.headlessServiceName\" . }}" in statefulset
    assert "volumeClaimTemplates:" in statefulset
    assert "WAVEMIND_DB" in statefulset
    assert "command:" in statefulset
    assert "- wavemind" in statefulset
    assert "- serve" in statefulset
    assert "WAVEMIND_RECOVERY_JOURNAL" in statefulset
    assert "WAVEMIND_STORE" in statefulset
    assert "WAVEMIND_POSTGRES_DSN" in statefulset
    assert "WAVEMIND_QDRANT_URL" in statefulset
    assert "WAVEMIND_QDRANT_API_KEY" in statefulset
    assert "WAVEMIND_REDIS_URL" in statefulset
    assert "WAVEMIND_API_KEYS" in statefulset
    assert "WAVEMIND_ADMIN_KEYS" in statefulset
    assert "WAVEMIND_REQUIRE_PRODUCTION_ADMISSION" in statefulset
    assert "WAVEMIND_PRODUCTION_TARGET_MEMORIES" in statefulset
    assert "WAVEMIND_PRODUCTION_ADMISSION_ROOT" in statefulset
    assert "path: /healthz" in statefulset
    assert "kind: Service" in service
    assert "clusterIP: None" in headless
    assert "publishNotReadyAddresses: true" in headless


def test_helm_chart_repair_cronjob_wires_cluster_repair():
    cronjob = read_chart_file("templates/repair-cronjob.yaml")

    assert "kind: CronJob" in cronjob
    assert "cluster-repair" in cronjob
    assert "--replication-factor" in cronjob
    assert "--write-quorum" in cronjob
    assert "--read-quorum" in cronjob
    assert "--node" in cronjob
    assert "until (int .Values.replicaCount)" in cronjob
    assert "svc.cluster.local" in cronjob
    assert "WAVEMIND_API_KEY" in cronjob
    assert "--namespace-prefix" in cronjob
    assert "--namespace-count" in cronjob


def test_helm_chart_memory_os_cronjob_wires_api_scheduler_and_worker():
    cronjob = read_chart_file("templates/memory-os-cronjob.yaml")
    values = read_chart_file("values.yaml")
    readme = read_chart_file("README.md")

    assert "{{- if .Values.memoryOs.enabled }}" in cronjob
    assert "kind: CronJob" in cronjob
    assert "app.kubernetes.io/component: memory-os" in cronjob
    assert "/memory-os/plan" in cronjob
    assert "/memory-os/run" in cronjob
    assert "strictPlan" in cronjob
    assert "runOnAllReplicas" in cronjob
    assert "WAVEMIND_API_KEY" in cronjob
    assert "svc.cluster.local" in cronjob
    assert "memoryOs:" in values
    assert "cacheMode: auto" in values
    assert "lockRequired: false" in values
    assert "lockTtlSeconds: 300" in values
    assert "idempotencyTtlSeconds: 604800" in values
    assert "backoffLimit: 3" in values
    assert "activeDeadlineSeconds: 600" in values
    assert 'emergencyStop: "false"' in values
    assert "suspend: false" in values
    assert "WAVEMIND_MEMORY_OS_RUN_ID" in cronjob
    assert "WAVEMIND_MEMORY_OS_EMERGENCY_STOP" in cronjob
    assert '"reason": "emergency_stop"' in cronjob
    assert 'run_payload["idempotency_key"]' in cronjob
    assert "lockPrefix: wavemind:memory-os:lock" in values
    assert "lock_required" in cronjob
    assert "lock_ttl_seconds" in cronjob
    assert "lock_prefix" in cronjob
    assert "plan_tasks" in cronjob
    assert "requires_distributed_lock" in cronjob
    assert "plan_requires_lock" in cronjob
    assert "memory-os-plan requires Redis" in cronjob
    assert "policy_auto_adjustments" in cronjob
    assert "--set memoryOs.enabled=true" in readme
    assert "--set memoryOs.lockRequired=true" in readme
    assert "--set memoryOs.runOnAllReplicas=false" in readme
    assert "task plan before mutation" in readme
    assert "`runtime.redisUrl` is not configured" in readme


def test_helm_chart_hpa_is_optional_and_targets_statefulset():
    hpa = read_chart_file("templates/hpa.yaml")
    readme = read_chart_file("README.md")

    assert "HorizontalPodAutoscaler" in hpa
    assert "{{- if .Values.autoscaling.enabled }}" in hpa
    assert "kind: StatefulSet" in hpa
    assert "targetCPUUtilizationPercentage" in hpa
    assert "targetMemoryUtilizationPercentage" in hpa
    assert "--set autoscaling.enabled=true" in readme


def test_helm_chart_documents_production_admission_startup_guard():
    readme = read_chart_file("README.md")
    values = read_chart_file("values.yaml")
    statefulset = read_chart_file("templates/statefulset.yaml")

    assert "productionAdmission:" in values
    assert "targetMemories: 0" in values
    assert "The API container starts through `wavemind serve`" in readme
    assert "--set productionAdmission.enabled=true" in readme
    assert "--set productionAdmission.targetMemories=100000000" in readme
    assert "before opening port 8000" in readme
    assert "{{- if .Values.productionAdmission.enabled }}" in statefulset
    assert ".Values.productionAdmission.targetMemories" in statefulset
    assert ".Values.productionAdmission.evidenceRoot" in statefulset


def test_helm_chart_auth_secret_is_optional_but_supported():
    secret = read_chart_file("templates/secret.yaml")
    values = read_chart_file("values.yaml")
    readme = read_chart_file("README.md")

    assert "auth:" in values
    assert "enabled: false" in values
    assert "existingSecret" in values
    assert "required \"auth.adminKey is required" in secret
    assert "kubectl create secret generic wavemind-auth" in readme
    assert "--set auth.existingSecret=wavemind-auth" in readme


def test_helm_chart_requires_secret_backed_production_backends():
    values = read_chart_file("values.yaml")
    statefulset = read_chart_file("templates/statefulset.yaml")
    readme = read_chart_file("README.md")

    assert "backends:" in values
    assert "backends.postgres.existingSecret is required" in statefulset
    assert "backends.qdrant.existingSecret is required" in statefulset
    assert "backends.redis.existingSecret is required" in statefulset
    assert "runtime.store=postgres" in readme
    assert "runtime.index=qdrant" in readme
    assert "wavemind-postgres" in readme
    assert "wavemind-qdrant" in readme
    assert "wavemind-redis" in readme


def test_helm_chart_files_do_not_contain_tabs_and_document_official_registry():
    for path in CHART_ROOT.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "\t" not in text, f"tab indentation in {path}"
    readme = read_chart_file("README.md")
    assert "official GitHub Container Registry image" in readme
    assert re.search(r"ghcr\.io/caspiang/wavemind", read_chart_file("values.yaml"), re.IGNORECASE)


def test_helm_chart_is_checked_by_github_actions():
    workflow = Path(".github/workflows/full-check.yml").read_text(encoding="utf-8")

    assert "helm:" in workflow
    assert "azure/setup-helm" in workflow
    assert "helm lint deploy/helm/wavemind" in workflow
    assert "helm template wavemind deploy/helm/wavemind" in workflow
    assert "grep -q \"kind: StatefulSet\"" in workflow
    assert "grep -q \"kind: CronJob\"" in workflow
    assert "grep -q \"kind: HorizontalPodAutoscaler\"" in workflow
    assert "--set memoryOs.enabled=true" in workflow
    assert "grep -q \"memory-os\"" in workflow
    assert "INSTALL_PRODUCTION=true" in Path(".github/workflows/container.yml").read_text(encoding="utf-8")
    assert "grep -q \"WAVEMIND_POSTGRES_DSN\"" in workflow
    assert "grep -q \"WAVEMIND_QDRANT_URL\"" in workflow
