from __future__ import annotations

import json
import re

from benchmarks.developer_experience_admission import (
    render_markdown,
    run_admission,
)


EXPECTED_CHECKS = {
    "starter-templates",
    "first-experience-packet",
    "persistent-idempotent-packet",
    "doctor",
    "safe-overwrite",
    "python-mcp-syntax",
    "typescript-syntax",
    "docker-compose-config",
}


def test_developer_experience_admission_is_strict_and_serializable():
    payload = run_admission()

    assert payload["schema"] == "wavemind.developer_experience_admission.v1"
    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", payload["source_sha"])
    assert payload["summary"]["checks_passed"] == 8
    assert payload["summary"]["checks_total"] == 8
    assert payload["summary"]["first_packet_seconds"] <= 300
    assert {check["id"] for check in payload["checks"]} == EXPECTED_CHECKS
    assert all(check["passed"] for check in payload["checks"])
    json.dumps(payload, allow_nan=False)


def test_developer_experience_admission_markdown_keeps_claim_boundary():
    payload = run_admission()

    rendered = render_markdown(payload)

    assert "# WaveMind Developer Experience Admission" in rendered
    assert "Status: **admitted**" in rendered
    assert "Checks: **8/8**" in rendered
    assert payload["claim_boundary"] in rendered
