from __future__ import annotations

import copy

from scripts.sync_product_status import consistency_errors, load_status


def test_canonical_product_status_matches_packages_and_public_docs():
    status = load_status()

    assert status["schema"] == "wavemind.product_status.v1"
    assert consistency_errors(status) == []
    assert status["safe_product"]["checked_in_status"] == "historical"
    assert status["stable_release"]["publication_status"] == "published"
    assert status["public_release"]["version"] == "2.13.0"
    assert status["public_release"]["source_sha"] == status["stable_release"]["source_sha"]
    assert status["release_candidate"]["blocker"] is None
    assert status["typescript"]["package_name"] == "@wavemind/http"
    assert status["typescript"]["npm_published"] is False


def test_product_status_rejects_version_and_npm_claim_drift():
    status = load_status()
    drifted = copy.deepcopy(status)
    drifted["stable_release"]["version"] = "999.0.0"
    drifted["typescript"]["npm_published"] = True

    errors = consistency_errors(drifted)

    assert any("expected 999.0.0" in error for error in errors)
    assert "npm publication claim must remain disabled until verified" in errors
