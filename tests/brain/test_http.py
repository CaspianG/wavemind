"""Real transport authority, strict input and browser session boundaries."""

import base64
import importlib.util

import pytest
from fastapi.testclient import TestClient

from wavemind.brain.models import BrainError
from wavemind.brain.service import BrainService


def test_authenticated_transport_is_available():
    assert importlib.util.find_spec("wavemind.brain.auth") is not None
    assert importlib.util.find_spec("wavemind.brain.http") is not None


def test_source_cap_is_composite_immutable_and_survives_serialization(tmp_path):
    from wavemind.brain.models import Principal
    from wavemind.brain.experience_bridge import principal_data

    service = BrainService(tmp_path)
    owner = Principal("owner")
    first = service.create_brain(principal=owner, title="First")["id"]
    second = service.create_brain(principal=owner, title="Second")["id"]
    with service.store.transaction(write=True) as conn:
        for brain in (first, second):
            conn.execute(
                "INSERT INTO sources(brain_id,id,title) VALUES (?,?,?)",
                (brain, "same_id", "visible only in first"),
            )
    refs = [[first, "same_id"]]
    scoped = Principal("owner", source_refs=refs)
    refs.append([second, "same_id"])
    assert len(service.list_sources(principal=scoped, brain_id=first)) == 1
    assert service.list_sources(principal=scoped, brain_id=second) == []
    assert Principal(**principal_data(scoped)) == scoped
    service.close()


def test_initial_audience_bound_and_existing_acl_preserved(tmp_path):
    from wavemind.brain.models import Principal

    service, owner, reader = (
        BrainService(tmp_path),
        Principal("owner"),
        Principal("reader"),
    )
    brain = service.create_brain(principal=owner, title="Atomic")["id"]
    service.set_member(
        principal=owner, brain_id=brain, identity=reader.identity, role="reader"
    )
    files = [{"name": "private.md", "content": b"Private commit"}]
    preview = service.preview_import(
        principal=owner, brain_id=brain, files=files, new_source_readers=[]
    )
    assert preview["new_source_access"] == {"mode": "restricted", "readers": []}
    result = service.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=preview["id"],
        accepted_ids=[preview["files"][0]["id"]],
    )
    assert service.list_sources(principal=reader, brain_id=brain) == []
    assert result["sources"][0]["access"] == {"mode": "restricted", "readers": []}
    ordinary = service.preview_import(principal=owner, brain_id=brain, files=files)
    assert ordinary["files"][0]["access"] == {"mode": "restricted", "readers": []}
    retry = service.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=ordinary["id"],
        accepted_ids=[ordinary["files"][0]["id"]],
    )
    assert retry["sources"][0]["id"] == result["sources"][0]["id"]
    assert service.list_sources(principal=reader, brain_id=brain) == []
    with pytest.raises(BrainError):
        service.preview_import(
            principal=owner,
            brain_id=brain,
            files=files,
            new_source_readers=[reader.identity],
        )
    service.close()


def test_http_rejects_overflow_and_unpaired_unicode(profile):
    *_, secret, brain, client = profile
    for raw in [b'{"question":"x","moment":1e309}', b'{"question":"\\ud800"}']:
        response = client.post(
            f"/brain/api/{brain}/context",
            headers={**headers(secret), "Content-Type": "application/json"},
            content=raw,
        )
        assert response.status_code == 422


@pytest.fixture
def profile(tmp_path):
    from wavemind.brain.auth import BrainAuth
    from wavemind.api import create_app

    auth = BrainAuth(tmp_path)
    secret = auth.bootstrap_owner()
    owner = auth.authenticate(secret)
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    brain = service.create_brain(principal=owner, title="Transport notes")["id"]
    app = create_app(brain_service=service, brain_auth=auth, brain_only=True)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:

        class Profile(tuple):
            def __repr__(self):
                return "Brain fixture (credentials redacted)"

        yield Profile((service, auth, owner, secret, brain, client))


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def upload(client, token, brain, text="Transport evidence", **extra):
    result = client.post(
        f"/brain/api/{brain}/sources/preview",
        headers=headers(token),
        json={
            "files": [
                {
                    "name": "evidence.md",
                    "content_base64": base64.b64encode(text.encode()).decode(),
                }
            ],
            **extra,
        },
    )
    assert result.status_code == 200, result.text
    preview = result.json()
    result = client.post(
        f"/brain/api/{brain}/sources/commit",
        headers=headers(token),
        json={
            "preview_id": preview["id"],
            "accepted_ids": [f["id"] for f in preview["files"]],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()["sources"][0]


def test_http_rejects_body_authority_and_unauthenticated_reads(profile):
    service, auth, owner, secret, brain, client = profile
    agent = auth.issue_agent(
        principal=owner, brain_ids=[brain], operations=["read"], label="Reader"
    )
    assert client.get(f"/brain/api/{brain}/memory").status_code == 401
    response = client.post(
        f"/brain/api/{brain}/claims/review",
        headers=headers(agent["token"]),
        json={
            "principal": {"identity": owner.identity},
            "claim_ids": [],
            "action": "approve",
        },
    )
    assert response.status_code == 422
    assert (
        client.get(
            f"/brain/api/{brain}/memory", headers=headers(agent["token"])
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/brain/api/{brain}/dependencies/recheck",
            headers=headers(agent["token"]),
            json={},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/brain/api/{brain}/dependencies/recheck", headers=headers(secret), json={}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/brain/api/{brain}/memory/review",
            headers=headers(agent["token"]),
            json={
                "record_type": "entity",
                "record_ids": [],
                "action": "approve",
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "bad_headers",
    [
        {"Host": "evil.example"},
        {"Host": "127.0.0.1.evil.example"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
    ],
)
def test_host_and_origin_rejected(profile, bad_headers):
    *_, secret, brain, client = profile
    response = client.get(
        "/brain/api/brains", headers={**headers(secret), **bad_headers}
    )
    assert response.status_code == 403


def test_strict_json_and_paths(profile):
    *_, secret, brain, client = profile
    for body in [
        '{"title":"a","title":"b"}',
        '{"title": NaN}',
        "[]",
        '{"title":1}',
        '{"title":"a","path":"C:/x"}',
    ]:
        response = client.post(
            "/brain/api/brains",
            headers={**headers(secret), "Content-Type": "application/json"},
            content=body,
        )
        assert response.status_code == 422
    response = client.post(
        f"/brain/api/{brain}/sources/preview",
        headers=headers(secret),
        json={"files": [{"name": "x.md", "path": "C:/x"}]},
    )
    assert response.status_code == 422
    assert (
        client.get(
            "/brain/api/brains?token=forbidden", headers=headers(secret)
        ).status_code
        == 422
    )


def test_session_csrf_live_revocation_and_expiry(profile):
    _, auth, owner, secret, brain, client = profile
    result = client.post("/brain/api/login", json={"secret": secret})
    assert result.status_code == 200
    csrf = result.json()["csrf_token"]
    assert "httponly" in result.headers["set-cookie"].lower()
    assert "samesite=strict" in result.headers["set-cookie"].lower()
    assert client.get("/brain/api/brains").status_code == 200
    assert (
        client.post("/brain/api/brains", json={"title": "Rejected"}).status_code == 403
    )
    assert (
        client.post(
            "/brain/api/brains",
            headers={"X-Brain-CSRF": csrf},
            json={"title": "Accepted"},
        ).status_code
        == 200
    )
    auth.revoke_token(principal=owner, token_id=auth.token_id(secret))
    assert client.get("/brain/api/brains").status_code == 401


def test_session_bootstrap_recovers_page_state_two_tabs_and_restart(
    profile, tmp_path, monkeypatch
):
    from wavemind.brain.auth import BrainAuth
    from wavemind.api import create_app
    import wavemind.brain.auth as auth_module

    _, _, owner, secret, _, client = profile
    login = client.post("/brain/api/login", json={"secret": secret})
    assert login.status_code == 200
    cookie = client.cookies.get("brain_session")
    first = client.get("/brain/api/session", headers={"Sec-Fetch-Site": "same-origin"})
    assert first.status_code == 200
    assert set(first.json()) == {"csrf_token", "expires_in", "identity", "kind"}
    assert first.json()["csrf_token"] == login.json()["csrf_token"]
    assert first.json()["identity"] == owner.identity
    assert 0 < first.json()["expires_in"] <= 3600
    assert "no-store" in first.headers["cache-control"]
    assert "access-control-allow-origin" not in first.headers
    for value in ["same-site", "cross-site", "none"]:
        assert (
            client.get(
                "/brain/api/session", headers={"Sec-Fetch-Site": value}
            ).status_code
            == 403
        )
    assert client.get("/brain/api/session?token=forbidden").status_code == 422
    assert (
        client.get(
            "/brain/api/session", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    now = auth_module.time.time()
    monkeypatch.setattr(auth_module.time, "time", lambda: now + 60)
    auth = BrainAuth(tmp_path)
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    with TestClient(
        create_app(brain_service=service, brain_auth=auth, brain_only=True),
        base_url="http://127.0.0.1:8000",
    ) as new_tab:
        new_tab.cookies.set("brain_session", cookie, path="/brain")
        second = new_tab.get("/brain/api/session")
        assert second.status_code == 200
        assert second.json()["csrf_token"] == first.json()["csrf_token"]
        assert second.json()["expires_in"] < first.json()["expires_in"]
        assert (
            new_tab.post(
                "/brain/api/brains",
                headers={"X-Brain-CSRF": second.json()["csrf_token"]},
                json={"title": "After reload"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/brain/api/brains",
                headers={"X-Brain-CSRF": first.json()["csrf_token"]},
                json={"title": "Other tab"},
            ).status_code
            == 200
        )


def test_session_bootstrap_does_not_revive_invalid_parent_or_cookie(
    profile, monkeypatch
):
    _, auth, owner, secret, _, client = profile
    assert client.get("/brain/api/session").status_code == 401
    assert (
        client.get(
            "/brain/api/session", headers={"Cookie": "brain_session=" + "f" * 43}
        ).status_code
        == 401
    )
    client.post("/brain/api/login", json={"secret": secret})
    auth.revoke_token(principal=owner, token_id=auth.token_id(secret))
    assert client.get("/brain/api/session").status_code == 401


def test_browser_session_expiry(profile, monkeypatch):
    import wavemind.brain.auth as auth_module

    _, _, _, secret, _, client = profile
    login = client.post("/brain/api/login", json={"secret": secret})
    assert login.status_code == 200
    now = auth_module.time.time()
    monkeypatch.setattr(auth_module.time, "time", lambda: now + 86401)
    assert client.get("/brain/api/brains").status_code == 401
    assert client.get("/brain/api/session").status_code == 401
    assert (
        client.post(
            "/brain/api/brains",
            headers={"X-Brain-CSRF": login.json()["csrf_token"]},
            json={"title": "Expired"},
        ).status_code
        == 401
    )


def test_body_size_rejected_before_json_parse(profile):
    *_, secret, _, client = profile
    response = client.post(
        "/brain/api/brains",
        headers={
            **headers(secret),
            "Content-Type": "application/json",
            "Content-Length": str(80 * 1024 * 1024),
        },
        content="invalid JSON",
    )
    assert response.status_code == 413
    response = client.post(
        "/brain/api/brains",
        headers={**headers(secret), "Content-Type": "application/json"},
        content=(b"x" * 65536 for _ in range(20)),
    )
    assert response.status_code == 413


def test_initial_restricted_import_is_atomic_and_bound_to_preview(profile):
    service, auth, owner, secret, brain, client = profile
    observer = auth.issue_agent(
        principal=owner,
        brain_ids=[brain],
        operations=["read"],
        label="Already authenticated",
    )
    principal = auth.authenticate(observer["token"])
    assert service.list_sources(principal=principal, brain_id=brain) == []
    imported = upload(
        client, secret, brain, "Private at initial commit", new_source_readers=[]
    )
    assert service.list_sources(principal=principal, brain_id=brain) == []
    with pytest.raises(BrainError, match="Resource not found"):
        service.read_citation(
            principal=principal,
            brain_id=brain,
            citation_id=imported["citations"][0]["id"],
        )
    response = client.post(
        f"/brain/api/{brain}/sources/preview",
        headers=headers(secret),
        json={
            "files": [
                {
                    "name": "copy.md",
                    "content_base64": base64.b64encode(
                        b"Private at initial commit"
                    ).decode(),
                }
            ]
        },
    )
    # A default-audience reimport cannot silently widen the existing source ACL.
    assert response.status_code in (200, 422)
    assert service.list_sources(principal=principal, brain_id=brain) == []


def test_human_owner_cannot_issue_agent_management_or_cross_brain_grants(profile):
    service, auth, owner, _, brain, _ = profile
    from wavemind.brain.models import Principal

    other = service.create_brain(
        principal=Principal("another_owner"), title="Unrelated"
    )["id"]
    for brain_ids, operations in [
        ([other], ["read"]),
        ([brain], ["manage_access"]),
        ([], ["read"]),
        ([brain], []),
    ]:
        with pytest.raises(BrainError):
            auth.issue_agent(
                principal=owner,
                brain_ids=brain_ids,
                operations=operations,
                label="Rejected",
            )


def test_agent_scopes_and_credentials_survive_restart_without_plaintext(
    profile, tmp_path
):
    service, auth, owner, secret, brain, client = profile
    first = upload(client, secret, brain)
    second = upload(client, secret, brain, "Other material")
    grant = auth.issue_agent(
        principal=owner,
        brain_ids=[brain],
        operations=["read", "export"],
        source_grants={brain: [first["id"]]},
        label="Scoped",
    )
    principal = auth.authenticate(grant["token"])
    assert principal.identity != owner.identity
    service.propose_claims(
        principal=owner,
        brain_id=brain,
        claims=[
            {
                "id": "mixed-origin",
                "kind": "fact",
                "key": "mixed",
                "content": "Requires both sources",
                "citation_ids": [
                    first["citations"][0]["id"],
                    second["citations"][0]["id"],
                ],
            }
        ],
    )
    service.review_claims(
        principal=owner, brain_id=brain, claim_ids=["mixed-origin"], action="approve"
    )
    exported = client.get(f"/brain/api/{brain}/export", headers=headers(grant["token"]))
    assert exported.status_code == 200
    assert len(exported.json()["records"]["chunks"]) == 1
    assert exported.json()["records"]["claims"] == []
    memory = client.get(f"/brain/api/{brain}/memory", headers=headers(grant["token"]))
    assert memory.status_code == 200
    assert memory.json()["claims"] == []
    assert (
        service.read_citation(
            principal=principal, brain_id=brain, citation_id=first["citations"][0]["id"]
        )["text"]
        == "Transport evidence"
    )
    with pytest.raises(BrainError, match="Resource not found"):
        service.read_citation(
            principal=principal,
            brain_id=brain,
            citation_id=second["citations"][0]["id"],
        )
    from wavemind.brain.auth import BrainAuth

    reopened = BrainAuth(tmp_path)
    assert reopened.authenticate(grant["token"]) == principal
    for path in tmp_path.glob("brain-auth.sqlite3*"):
        assert secret.encode() not in path.read_bytes()
        assert grant["token"].encode() not in path.read_bytes()
    reopened.close()


def test_http_complete_owner_review_action_outcome_and_scoped_history(profile):
    service, _, _, secret, brain, client = profile
    source = upload(client, secret, brain, "Check the orchard before launch")
    cid = source["citations"][0]["id"]

    def post(path, data, token=secret):
        response = client.post("/brain/api/" + path, headers=headers(token), json=data)
        assert response.status_code == 200, response.text
        return response.json()

    entity = post(
        f"{brain}/entities",
        {"kind": "project", "name": "Orchard", "citation_ids": [cid]},
    )
    assert entity["status"] == "proposed"
    reviewed = post(
        f"{brain}/memory/review",
        {"record_type": "entity", "record_ids": [entity["id"]], "action": "approve"},
    )
    assert reviewed[0]["status"] == "active"
    post(
        f"{brain}/claims/propose",
        {
            "claims": [
                {
                    "id": "orchard-goal",
                    "kind": "goal",
                    "key": "orchard",
                    "content": "Check the orchard",
                    "citation_ids": [cid],
                    "entity_ids": [entity["id"]],
                }
            ]
        },
    )
    assert (
        post(
            f"{brain}/claims/review",
            {"claim_ids": ["orchard-goal"], "action": "approve"},
        )[0]["status"]
        == "active"
    )
    issued = post(
        "credentials/agents",
        {
            "brain_ids": [brain],
            "operations": ["read", "record_outcome"],
            "label": "Reporting agent",
        },
    )
    token = issued["token"]
    packet = post(
        f"{brain}/context", {"question": "orchard", "project_id": entity["id"]}, token
    )
    assert packet["schema"] == "wavemind.brain_context.v1"
    assert packet["claims"][0]["id"] == "orchard-goal"
    post(f"{brain}/context/validate", {"packet_id": packet["id"]}, token)
    receipt = post(
        f"{brain}/actions",
        {"packet_id": packet["id"], "run_id": "http-run", "action": "Check orchard"},
        token,
    )
    outcome = post(
        f"{brain}/outcomes",
        {
            "receipt_id": receipt["id"],
            "outcome": {
                "idempotency_key": "http-result",
                "summary": "Check failed",
                "procedure": ["Check orchard"],
                "evidence_citation_ids": [cid],
            },
        },
        token,
    )
    assert outcome["status"] == "unverified"
    verify_body = {
        "success": False,
        "evidence_citation_ids": [cid],
        "note": "Negative check",
    }
    assert (
        client.post(
            f"/brain/api/{brain}/outcomes/{outcome['id']}/verify",
            headers=headers(token),
            json=verify_body,
        ).status_code
        == 404
    )
    verified = post(f"{brain}/outcomes/{outcome['id']}/verify", verify_body)
    assert verified["status"] == "failed"
    assert verified["verification"]["mode"] == "manual_attestation"
    history = client.get(
        f"/brain/api/{brain}/experience?limit=1", headers=headers(token)
    )
    assert history.status_code == 200
    assert history.json()["outcomes"][0]["reporter_id"] == issued["identity"]
    assert history.json()["outcomes"][0]["verification"]["success"] is False
    assert (
        client.get(
            f"/brain/api/{brain}/experience?limit=true", headers=headers(token)
        ).status_code
        == 422
    )
    assert (
        client.get(f"/brain/api/{brain}/export", headers=headers(token)).status_code
        == 404
    )
    exported = client.get(f"/brain/api/{brain}/export", headers=headers(secret))
    assert (
        exported.status_code == 200 and len(exported.json()["records"]["outcomes"]) == 1
    )
    service.register_outcome_verifier(
        verifier_id="local-check", source="test", callback=lambda data: True
    )
    packet = post(f"{brain}/context", {"question": "orchard"}, token)
    receipt = post(
        f"{brain}/actions",
        {"packet_id": packet["id"], "run_id": "http-run-2", "action": "Check again"},
        token,
    )
    outcome = post(
        f"{brain}/outcomes",
        {
            "receipt_id": receipt["id"],
            "outcome": {
                "idempotency_key": "result-2",
                "summary": "Checked",
                "procedure": [],
                "evidence_citation_ids": [cid],
            },
        },
        token,
    )
    result = post(
        f"{brain}/outcomes/{outcome['id']}/verify-with",
        {"verifier_id": "local-check", "evidence_citation_ids": [cid]},
    )
    assert result["verification"]["mode"] == "configured_verifier"
    assert (
        client.post(
            f"/brain/api/{brain}/outcomes/{outcome['id']}/verify-with",
            headers=headers(secret),
            json={
                "verifier_id": "local-check",
                "evidence_citation_ids": [cid],
                "callback": "http://forbidden",
            },
        ).status_code
        == 422
    )
    post(f"{brain}/sources/{source['id']}/revoke", {})
    assert (
        client.get(
            f"/brain/api/{brain}/citations/{cid}", headers=headers(token)
        ).status_code
        == 404
    )


def test_explicit_additive_source_grant_does_not_replace_other_readers(profile):
    service, auth, owner, secret, brain, client = profile
    selected = upload(
        client, secret, brain, "Selected private", new_source_readers=["existing"]
    )
    unselected = upload(
        client, secret, brain, "Unselected private", new_source_readers=["existing"]
    )
    capped = auth.issue_agent(
        principal=owner,
        brain_ids=[brain],
        operations=["read"],
        source_grants={brain: [selected["id"]]},
        label="Cap only",
    )
    assert capped["readable_source_refs"] == []
    granted = auth.issue_agent(
        principal=owner,
        brain_ids=[brain],
        operations=["read"],
        source_grants={brain: [selected["id"]]},
        grant_selected_sources=True,
        label="Explicit access",
    )
    assert granted["readable_source_refs"] == [[brain, selected["id"]]]
    with service.store.transaction() as conn:
        import json

        rows = {
            row["id"]: json.loads(row["readers_json"])
            for row in conn.execute(
                "SELECT id,readers_json FROM sources WHERE brain_id=?", (brain,)
            )
        }
    assert set(rows[selected["id"]]) == {"existing", granted["identity"]}
    assert rows[unselected["id"]] == ["existing"]
    auth.revoke_token(principal=owner, token_id=granted["token_id"])
    with pytest.raises(BrainError):
        auth.authenticate(granted["token"])


def test_pending_issuance_never_activates_after_failure_and_restart(
    profile, tmp_path, monkeypatch
):
    _, auth, owner, _, brain, _ = profile
    from wavemind.brain.auth import BrainAuth

    def crash(_):
        raise RuntimeError("simulated activation failure")

    monkeypatch.setattr(auth, "_activate", crash)
    with pytest.raises(RuntimeError):
        auth.issue_agent(
            principal=owner, brain_ids=[brain], operations=["read"], label="Interrupted"
        )
    reopened = BrainAuth(tmp_path)
    rows = reopened.list_tokens(principal=owner)
    assert [r["status"] for r in rows if r["label"] == "Interrupted"] == ["pending"]
    with reopened._transaction() as conn:
        pending = conn.execute(
            "SELECT id FROM credentials WHERE status='pending'"
        ).fetchone()[0]
        with pytest.raises(BrainError):
            reopened._live(conn, token_id=pending)
    reopened.close()


def test_membership_and_selected_acl_grants_rollback_together(profile, monkeypatch):
    import wavemind.brain.auth as auth_module
    import json

    service, auth, owner, secret, brain, client = profile
    source = upload(
        client, secret, brain, "Atomic selected grant", new_source_readers=["existing"]
    )
    real_change = auth_module.record_change

    def fail_acl_audit(conn, **values):
        if values["kind"] == "source_access_set":
            raise OSError("simulated authority write failure")
        return real_change(conn, **values)

    monkeypatch.setattr(auth_module, "record_change", fail_acl_audit)
    with pytest.raises(OSError):
        auth.issue_agent(
            principal=owner,
            brain_ids=[brain],
            operations=["read"],
            source_grants={brain: [source["id"]]},
            grant_selected_sources=True,
            label="Failed atomic grant",
        )
    row = next(
        r
        for r in auth.list_tokens(principal=owner)
        if r["label"] == "Failed atomic grant"
    )
    assert row["status"] == "pending"
    with service.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM members WHERE identity=?", (row["identity"],)
            ).fetchone()
            is None
        )
        acl = conn.execute(
            "SELECT readers_json FROM sources WHERE brain_id=? AND id=?",
            (brain, source["id"]),
        ).fetchone()[0]
        assert json.loads(acl) == ["existing"]


def test_provisional_session_csrf_migration_preserves_lifetime(profile):
    import hashlib

    _, auth, _, secret, _, client = profile
    client.post("/brain/api/login", json={"secret": secret})
    with auth._transaction() as conn:
        before = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]
        conn.execute(
            "UPDATE sessions SET csrf_digest=?",
            (hashlib.sha256(b"legacy-random-csrf").hexdigest(),),
        )
    first = client.get("/brain/api/session")
    assert first.status_code == 200
    second = client.get("/brain/api/session")
    assert first.json()["csrf_token"] == second.json()["csrf_token"]
    with auth._transaction() as conn:
        assert conn.execute("SELECT expires_at FROM sessions").fetchone()[0] == before
        conn.execute("UPDATE credentials SET expires_at=0")
    assert client.get("/brain/api/session").status_code == 401


def test_revocation_racing_pending_activation_cannot_report_live_grant(
    profile, monkeypatch
):
    _, auth, owner, _, brain, _ = profile
    activate = auth._activate

    def revoke_before_activation(token_id):
        auth.revoke_token(principal=owner, token_id=token_id)
        activate(token_id)

    monkeypatch.setattr(auth, "_activate", revoke_before_activation)
    with pytest.raises(BrainError):
        auth.issue_agent(
            principal=owner,
            brain_ids=[brain],
            operations=["read"],
            label="Concurrent revoke",
        )
    assert (
        next(
            row
            for row in auth.list_tokens(principal=owner)
            if row["label"] == "Concurrent revoke"
        )["status"]
        == "revoked"
    )


def test_revocation_preserves_explicitly_promoted_owner_membership(profile):
    service, auth, owner, _, brain, _ = profile
    issued = auth.issue_agent(
        principal=owner, brain_ids=[brain], operations=["read"], label="Promoted"
    )
    service.set_member(
        principal=owner, brain_id=brain, identity=issued["identity"], role="owner"
    )
    auth.revoke_token(principal=owner, token_id=issued["token_id"])
    with pytest.raises(BrainError):
        auth.authenticate(issued["token"])
    # Cleanup is best effort and must not perform an ownership transfer behind
    # the authority service's owner-retention rules.
    with service.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT role FROM members WHERE brain_id=? AND identity=?",
                (brain, issued["identity"]),
            ).fetchone()[0]
            == "owner"
        )


def test_revocation_survives_failed_membership_cleanup(profile, monkeypatch):
    service, auth, owner, _, brain, _ = profile
    first = auth.issue_agent(
        principal=owner, brain_ids=[brain], operations=["read"], label="Revoked"
    )
    other = auth.issue_agent(
        principal=owner, brain_ids=[brain], operations=["read"], label="Independent"
    )

    def fail(*args):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(auth, "_remove_memberships", fail)
    auth.revoke_token(principal=owner, token_id=first["token_id"])
    with pytest.raises(BrainError):
        auth.authenticate(first["token"])
    assert (
        service.list_brains(principal=auth.authenticate(other["token"]))[0]["id"]
        == brain
    )


def test_coexistence_legacy_query_cannot_read_brain(profile, tmp_path):
    service, auth, _, secret, brain, client = profile
    upload(client, secret, brain, "Brain-only hidden phrase")
    from wavemind import WaveMind
    from wavemind.api import create_app

    legacy = WaveMind(db_path=tmp_path / "legacy.sqlite3")
    with TestClient(
        create_app(mind=legacy, brain_service=service, brain_auth=auth),
        base_url="http://127.0.0.1:8000",
    ) as coexist:
        result = coexist.post("/query", json={"text": "Brain-only hidden phrase"})
        assert result.status_code == 200
        assert "Brain-only hidden phrase" not in result.text
        assert coexist.get("/brain/api/brains").status_code == 401
    legacy.close()


def test_dedicated_launch_has_no_legacy_routes_or_environment_side_effects(
    tmp_path, monkeypatch
):
    from wavemind.brain.auth import BrainAuth
    from wavemind.api import create_app

    for key in [
        "WAVEMIND_DB",
        "WAVEMIND_ENCODER",
        "WAVEMIND_STORE",
        "WAVEMIND_POSTGRES_DSN",
        "WAVEMIND_EXPERIENCE_DB",
    ]:
        monkeypatch.setenv(key, "must-not-be-opened")
    auth = BrainAuth(tmp_path)
    auth.bootstrap_owner()
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    with TestClient(
        create_app(brain_service=service, brain_auth=auth, brain_only=True),
        base_url="http://127.0.0.1:8000",
    ) as client:
        assert client.post("/query", json={"text": "private"}).status_code == 404
        assert client.post("/memories", json={"text": "private"}).status_code == 404
        assert client.get("/brain/api/brains").status_code == 401
    assert not (tmp_path / "brain-experience.sqlite3").exists()
