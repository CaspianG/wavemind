"""Behavioral import boundaries, provenance and source erasure tests."""

import io
import json
import subprocess
import sys
import time

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from wavemind.brain.models import BrainError, Principal
from wavemind.brain.service import BrainService


@pytest.fixture
def context(tmp_path):
    service, owner = BrainService(tmp_path), Principal("owner")
    brain = service.create_brain(principal=owner, title="Notes")["id"]
    yield service, owner, brain
    service.close()


def preview(s, owner, brain, content=b"Ship on Friday.", **fields):
    return s.preview_import(
        principal=owner,
        brain_id=brain,
        files=[dict(name="note.md", content=content, **fields)],
    )


def commit(s, owner, brain, p):
    return s.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=p["id"],
        accepted_ids=[f["id"] for f in p["files"]],
    )


def imported(s, owner, brain, content=b"Ship on Friday.", **fields):
    return commit(s, owner, brain, preview(s, owner, brain, content, **fields))[
        "sources"
    ][0]


def test_preview_commit_retry_and_exact_citation(context, tmp_path):
    s, owner, b = context
    p = preview(s, owner, b)
    assert p["network_calls"] == 0 and p["model_connected"] is False
    assert p["files"][0]["preview_text"] == "Ship on Friday."
    assert s.list_sources(principal=owner, brain_id=b) == []
    first = commit(s, owner, b, p)
    assert first == commit(s, owner, b, p)
    citation = first["sources"][0]["citations"][0]
    assert citation["text"] == "Ship on Friday."
    assert (citation["start"], citation["end"]) == (0, 15)
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert commit(reopened, owner, b, p) == first
        assert reopened.read_citation(
            principal=owner, brain_id=b, citation_id=citation["id"]
        ) == {**citation, "source_id": first["sources"][0]["id"], "version": 1}
    finally:
        reopened.close()


def test_digest_identity_and_explicit_versions(context):
    s, owner, b = context
    one = imported(s, owner, b)
    p = s.preview_import(
        principal=owner,
        brain_id=b,
        files=[{"name": "other.txt", "content": b"Ship on Friday."}],
    )
    assert commit(s, owner, b, p)["sources"][0] == one
    two = imported(s, owner, b, b"Ship on Monday.")
    assert two["id"] != one["id"]  # Same filename cannot silently update.
    changed = imported(s, owner, b, b"Ship on Tuesday.", source_id=one["id"])
    assert (changed["id"], changed["version"]) == (one["id"], 2)
    assert imported(s, owner, b, b"Ship on Tuesday.", source_id=one["id"]) == changed


def test_unicode_normalization_and_chunk_offsets(context):
    s, owner, b = context
    text = "Привет\n" + "🙂" * 3000 + "\nfin"
    source = imported(s, owner, b, text.replace("\n", "\r\n").encode())
    chunks = source["citations"]
    assert len(chunks) > 1
    assert "".join(c["text"] for c in chunks) == text
    assert chunks[0]["start"] == 0 and chunks[-1]["end"] == 3011
    for c in chunks:
        assert text[c["start"] : c["end"]] == c["text"]
        assert len(c["text"].encode()) <= 8192


@pytest.mark.parametrize(
    "files",
    [
        [],
        [{"name": "x.txt", "content": b"x"}] * 21,
        [{"name": "x.txt", "content": b"x", "path": "C:/secret.txt"}],
        [{"name": "../x.txt", "content": b"x"}],
        [{"name": "x.txt", "content": "text"}],
        [{"name": "x.txt", "content": b"x" * (10485760 + 1)}],
        [{"name": "x.txt", "content": b"x" * 10485760}] * 5
        + [{"name": "x.txt", "content": b"x"}],
    ],
)
def test_invalid_envelope_is_atomic(context, files):
    s, owner, b = context
    with pytest.raises(BrainError) as exc:
        s.preview_import(principal=owner, brain_id=b, files=files)
    assert exc.value.code == "invalid_input"
    assert s.list_sources(principal=owner, brain_id=b) == []


def test_literal_count_input_and_extracted_boundaries(context):
    s, owner, b = context
    p = s.preview_import(
        principal=owner, brain_id=b, files=[{"name": "x.txt", "content": b"x"}] * 20
    )
    assert len(p["files"]) == 20
    # JSON whitespace counts against uploaded bytes but not extracted text.
    payload = (
        b'{"schema":"wavemind.messages.v1","messages":[{"role":"user","content":"ok"}]}'
    )
    exact = payload + b" " * (10485760 - len(payload))
    p = s.preview_import(
        principal=owner, brain_id=b, files=[{"name": "x.json", "content": exact}] * 5
    )
    assert [f["status"] for f in p["files"]] == ["valid"] * 5
    exact_text = preview(s, owner, b, b"x" * 2097152)
    assert exact_text["files"][0]["extracted_bytes"] == 2097152
    over = preview(s, owner, b, b"x" * 2097153)
    assert over["files"][0]["error"] == "extracted_limit"
    unicode_over = preview(s, owner, b, ("🙂" * 524289).encode())
    assert unicode_over["files"][0]["error"] == "extracted_limit"


@pytest.mark.parametrize(
    "name,content",
    [
        ("a.zip", b"PK\x03\x04data"),
        ("a.txt", b"PK\x03\x04data"),
        ("a.txt", b"\xff"),
        ("a.md", b" \r\n\t"),
        ("a.pdf", b"broken"),
        ("a.json", b'{"schema":"unknown","messages":[]}'),
        ("a.json", b'{"schema":"wavemind.messages.v1","messages":[]}'),
        (
            "a.json",
            b'{"schema":"wavemind.messages.v1","messages":[{"role":"user","content":2}]}',
        ),
        (
            "a.json",
            b'{"schema":"wavemind.messages.v1","messages":[{"role":"owner","content":"x"}]}',
        ),
        (
            "a.json",
            b'{"schema":"wavemind.messages.v1","messages":[{"role":"user","content":"x","extra":1}]}',
        ),
        (
            "a.json",
            b'{"schema":"wavemind.messages.v1","messages":[{"role":"user","content":"x","timestamp":true}]}',
        ),
        (
            "a.json",
            b'{"schema":"wavemind.messages.v1","messages":[{"role":"user","content":"x","timestamp":NaN}]}',
        ),
        (
            "a.json",
            b'{"schema":"wavemind.messages.v1","schema":"wavemind.messages.v1","messages":[]}',
        ),
    ],
)
def test_invalid_parses_visible_and_cannot_commit(context, name, content):
    s, owner, b = context
    p = s.preview_import(
        principal=owner,
        brain_id=b,
        files=[
            {"name": "good.txt", "content": b"Good"},
            {"name": name, "content": content},
        ],
    )
    assert p["files"][1]["status"] == "error"
    assert p["files"][1]["preview_text"] == ""
    with pytest.raises(BrainError):
        commit(s, owner, b, p)
    assert s.list_sources(principal=owner, brain_id=b) == []
    result = s.commit_import(
        principal=owner,
        brain_id=b,
        preview_id=p["id"],
        accepted_ids=[p["files"][0]["id"]],
    )
    assert result["sources"][0]["citations"][0]["text"] == "Good"


def pdf_bytes(*, blank=False, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if not blank:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 10 200 Td (Ship on Friday.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_and_message_import(context):
    s, owner, b = context
    p = s.preview_import(
        principal=owner,
        brain_id=b,
        files=[
            {"name": "note.pdf", "content": pdf_bytes()},
            {"name": "blank.pdf", "content": pdf_bytes(blank=True)},
            {"name": "secret.pdf", "content": pdf_bytes(encrypted=True)},
            {
                "name": "chat.json",
                "content": json.dumps(
                    {
                        "schema": "wavemind.messages.v1",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Hello\r\nworld",
                                "timestamp": 123.5,
                            },
                            {"role": "assistant", "content": "Привет"},
                        ],
                    }
                ).encode(),
            },
        ],
    )
    assert [f["status"] for f in p["files"]] == ["valid", "error", "error", "valid"]
    assert p["files"][0]["preview_text"] == "Ship on Friday."
    assert p["files"][3]["preview_text"] == "user: Hello\nworld\nassistant: Привет"


def test_pdf_worker_hard_timeout_and_cleanup(tmp_path, monkeypatch):
    from wavemind.brain import parsing

    # Real process termination with a short clock; slow parser double is needed
    # to exercise a deterministic timeout without keeping a malicious PDF.
    processes = []
    real_popen = subprocess.Popen

    def slow_worker(*args, **kwargs):
        process = real_popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(parsing.subprocess, "Popen", slow_worker)
    monkeypatch.setattr(parsing, "PARSE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(BrainError) as exc:
        parsing.parse_file(name="a.pdf", content=pdf_bytes())
    assert exc.value.code == "parse_timeout"
    assert all(p.poll() is not None for p in processes)


def test_timeout_literal_budget(context, monkeypatch):
    from wavemind.brain import parsing

    real_popen = subprocess.Popen
    waits = []

    class TimedProcess:
        def __init__(self, *args, **kwargs):
            self.child = real_popen(*args, **kwargs)

        def wait(self, timeout=None):
            waits.append(timeout)
            return self.child.wait(timeout=timeout)

        def kill(self):
            self.child.kill()

        @property
        def returncode(self):
            return self.child.returncode

    monkeypatch.setattr(parsing.subprocess, "Popen", TimedProcess)
    assert parsing.parse_file(name="a.pdf", content=pdf_bytes())[0] == "Ship on Friday."
    assert len(waits) == 1 and 29 < waits[0] <= 30


def test_preview_creator_expiry_cancellation_and_live_rights(context):
    s, owner, b = context
    editor = Principal("editor")
    s.set_member(principal=owner, brain_id=b, identity="editor", role="editor")
    p = preview(s, owner, b)
    with pytest.raises(BrainError) as exc:
        commit(s, editor, b, p)
    assert exc.value.code == "not_found"
    assert s.commit_import(
        principal=owner, brain_id=b, preview_id=p["id"], accepted_ids=[]
    ) == {"sources": []}
    with pytest.raises(BrainError):
        commit(s, owner, b, p)
    p = preview(s, owner, b)
    with s.store.transaction(write=True) as conn:
        conn.execute(
            "UPDATE previews SET expires_at=? WHERE id=?", (time.time() - 1, p["id"])
        )
    with pytest.raises(BrainError):
        commit(s, owner, b, p)
    p = preview(s, editor, b)
    s.set_member(principal=owner, brain_id=b, identity="editor", role=None)
    with pytest.raises(BrainError) as exc:
        commit(s, editor, b, p)
    assert exc.value.code == "not_found"


def test_cross_brain_and_acl_fail_closed(context):
    s, owner, b = context
    source = imported(s, owner, b)
    other = s.create_brain(principal=owner, title="Other")["id"]
    with pytest.raises(BrainError) as exc:
        s.read_citation(
            principal=owner, brain_id=other, citation_id=source["citations"][0]["id"]
        )
    assert exc.value.code == "not_found"
    s.set_member(principal=owner, brain_id=b, identity="editor", role="editor")
    editor = Principal("editor")
    pending = preview(s, editor, b, b"Changed", source_id=source["id"])
    s.set_source_access(principal=owner, brain_id=b, source_id=source["id"], readers=[])
    assert s.list_sources(principal=editor, brain_id=b) == []
    for operation in [
        lambda: commit(s, editor, b, pending),
        lambda: preview(s, editor, b),
        lambda: s.read_citation(
            principal=editor, brain_id=b, citation_id=source["citations"][0]["id"]
        ),
    ]:
        with pytest.raises(BrainError) as exc:
            operation()
        assert exc.value.code == "not_found"
    with s.store.transaction() as conn:
        assert (
            "Changed"
            not in conn.execute(
                "SELECT payload_json FROM previews WHERE id=?", (pending["id"],)
            ).fetchone()[0]
        )


@pytest.mark.parametrize("action", ["revoke", "delete"])
def test_lifecycle_purges_linked_records_and_retries(context, tmp_path, action):
    s, owner, b = context
    source = imported(s, owner, b, b"PRIVATE SOURCE")
    pending = preview(s, owner, b, b"PRIVATE UPDATE", source_id=source["id"])
    payload = '{"text":"PRIVATE DERIVED"}'
    with s.store.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO claims(brain_id,id,kind,status,payload_json) VALUES (?,'c','fact','active',?)",
            (b, payload),
        )
        conn.execute(
            "INSERT INTO packets(brain_id,id,principal_id,revision,digest,payload_json) VALUES (?,'p','owner',1,'d',?)",
            (b, payload),
        )
        conn.execute(
            "INSERT INTO receipts(brain_id,id,packet_id,principal_id,packet_digest,payload_json) VALUES (?,'r','p','owner','d',?)",
            (b, payload),
        )
        conn.execute(
            "INSERT INTO outcomes(brain_id,id,receipt_id,payload_json) VALUES (?,'o','r',?)",
            (b, payload),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'claim','c','source',?,?)",
            (b, source["id"], source["id"]),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'packet','p','claim','c',?)",
            (b, source["id"]),
        )
    result = s.change_source(
        principal=owner, brain_id=b, source_id=source["id"], action=action
    )
    assert result["status"] == ("deleted" if action == "delete" else "revoked")
    with pytest.raises(BrainError):
        commit(s, owner, b, pending)
    with pytest.raises(BrainError) as exc:
        s.read_citation(
            principal=owner, brain_id=b, citation_id=source["citations"][0]["id"]
        )
    assert exc.value.code == "not_found"
    with s.store.transaction() as conn:
        for table in (
            ("claims", "packets", "receipts", "outcomes", "previews")
            if action == "delete"
            else ("previews",)
        ):
            assert all(
                "PRIVATE" not in row[0]
                for row in conn.execute(
                    f"SELECT payload_json FROM {table} WHERE brain_id=?", (b,)
                )
            )
        if action == "revoke":
            for table in ("claims", "packets", "receipts", "outcomes"):
                assert (
                    conn.execute(
                        f"SELECT payload_json FROM {table} WHERE brain_id=?", (b,)
                    ).fetchone()[0]
                    == payload
                )
        assert (
            conn.execute("SELECT status FROM claims WHERE id='c'").fetchone()[0]
            == "revoked"
        )
        assert (
            conn.execute("SELECT status FROM packets WHERE id='p'").fetchone()[0]
            == "revoked"
        )
        assert all(
            "PRIVATE" not in row[0]
            for row in conn.execute("SELECT payload_json FROM outbox")
        )
        if action == "delete":
            assert (
                conn.execute(
                    "SELECT count(*) FROM chunks WHERE source_id=?", (source["id"],)
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM source_versions WHERE source_id=?",
                    (source["id"],),
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT title FROM sources WHERE id=?", (source["id"],)
                ).fetchone()[0]
                == ""
            )
            assert conn.execute("SELECT count(*) FROM tombstones").fetchone()[0] == 1
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert reopened.list_sources(principal=owner, brain_id=b) == []
        assert (
            reopened.change_source(
                principal=owner, brain_id=b, source_id=source["id"], action=action
            )
            == result
        )
    finally:
        reopened.close()


def test_pause_resume_and_agent_cannot_manage(context):
    s, owner, b = context
    source = imported(s, owner, b)
    result = s.change_source(
        principal=owner, brain_id=b, source_id=source["id"], action="pause"
    )
    assert result["status"] == "paused"
    assert (
        s.read_citation(
            principal=owner, brain_id=b, citation_id=source["citations"][0]["id"]
        )["text"]
        == "Ship on Friday."
    )
    with pytest.raises(BrainError):
        imported(s, owner, b, b"updated", source_id=source["id"])
    assert (
        s.change_source(
            principal=owner, brain_id=b, source_id=source["id"], action="resume"
        )["status"]
        == "active"
    )
    agent = Principal(
        "owner", "agent", frozenset({b}), frozenset({"import", "read", "delete"})
    )
    with pytest.raises(BrainError) as exc:
        s.change_source(
            principal=agent, brain_id=b, source_id=source["id"], action="delete"
        )
    assert exc.value.code == "not_found"


def test_worker_start_failure_is_a_visible_sanitized_parse_error(context, monkeypatch):
    from wavemind.brain import parsing

    def unavailable(*args, **kwargs):
        raise OSError("PRIVATE runtime details")

    monkeypatch.setattr(parsing.subprocess, "Popen", unavailable)
    s, owner, b = context
    p = s.preview_import(
        principal=owner, brain_id=b, files=[{"name": "a.pdf", "content": pdf_bytes()}]
    )
    assert p["files"][0]["status"] == "error"
    assert p["files"][0]["error"] == "parser_unavailable"
    assert "PRIVATE" not in json.dumps(p)


def test_unencodable_name_is_a_domain_error(context):
    s, owner, b = context
    with pytest.raises(BrainError) as exc:
        s.preview_import(
            principal=owner,
            brain_id=b,
            files=[{"name": "bad\ud800.txt", "content": b"valid"}],
        )
    assert exc.value.code == "invalid_input"


def test_preview_capacity_cancellation_and_expiration_reclaim_slots(context):
    s, owner, b = context
    pending = [preview(s, owner, b) for _ in range(5)]
    with pytest.raises(BrainError) as exc:
        preview(s, owner, b)
    assert exc.value.code == "preview_limit"
    s.commit_import(
        principal=owner, brain_id=b, preview_id=pending[0]["id"], accepted_ids=[]
    )
    preview(s, owner, b)
    with s.store.transaction(write=True) as conn:
        conn.execute("UPDATE previews SET expires_at=0 WHERE id=?", (pending[1]["id"],))
    preview(s, owner, b)
    with s.store.transaction() as conn:
        assert conn.execute(
            "SELECT status,payload_json FROM previews WHERE id=?", (pending[1]["id"],)
        ).fetchone()[:] == ("expired", "{}")


def test_competing_source_updates_are_atomic_and_old_previews_are_invalidated(context):
    s, owner, b = context
    source = imported(s, owner, b)
    competing = s.preview_import(
        principal=owner,
        brain_id=b,
        files=[
            {"name": "a.txt", "content": b"Monday", "source_id": source["id"]},
            {"name": "b.txt", "content": b"Tuesday", "source_id": source["id"]},
        ],
    )
    with pytest.raises(BrainError):
        commit(s, owner, b, competing)
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT max(version) FROM source_versions WHERE source_id=?",
                (source["id"],),
            ).fetchone()[0]
            == 1
        )
    updated = imported(s, owner, b, b"Wednesday", source_id=source["id"])
    assert updated["version"] == 2
    with pytest.raises(BrainError):
        s.commit_import(
            principal=owner,
            brain_id=b,
            preview_id=competing["id"],
            accepted_ids=[competing["files"][0]["id"]],
        )
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT payload_json FROM previews WHERE id=?", (competing["id"],)
            ).fetchone()[0]
            == "{}"
        )
    assert (
        s.read_citation(
            principal=owner, brain_id=b, citation_id=source["citations"][0]["id"]
        )["text"]
        == "Ship on Friday."
    )


def test_recheck_authority_after_parsing_without_holding_database_lock(
    context, tmp_path, monkeypatch
):
    from wavemind.brain import sources

    s, owner, b = context
    s.set_member(principal=owner, brain_id=b, identity="editor", role="editor")
    other = BrainService(tmp_path)
    real_parse = sources.parse_file

    def revoke_during_parse(**kwargs):
        other.set_member(principal=owner, brain_id=b, identity="editor", role=None)
        return real_parse(**kwargs)

    monkeypatch.setattr(sources, "parse_file", revoke_during_parse)
    try:
        with pytest.raises(BrainError) as exc:
            preview(s, Principal("editor"), b)
        assert exc.value.code == "not_found"
        with s.store.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM previews").fetchone()[0] == 0
    finally:
        other.close()


def test_selected_unknown_or_duplicate_ids_cannot_partially_import(context):
    s, owner, b = context
    p = preview(s, owner, b)
    fid = p["files"][0]["id"]
    for accepted in ([fid, "unknown"], [fid, fid], [None], "invalid"):
        with pytest.raises(BrainError):
            s.commit_import(
                principal=owner, brain_id=b, preview_id=p["id"], accepted_ids=accepted
            )
    assert s.list_sources(principal=owner, brain_id=b) == []
    assert commit(s, owner, b, p)["sources"][0]["version"] == 1


@pytest.mark.parametrize(
    "action,status",
    [
        ("access", "active"),
        ("update", "proposed"),
        ("revoke", "revoked"),
        ("delete", "revoked"),
    ],
)
def test_lifecycle_retains_reviewable_history_except_delete(context, action, status):
    s, owner, b = context
    source = imported(s, owner, b)
    untouched = imported(s, owner, b, b"Other source")
    with s.store.transaction(write=True) as conn:
        for kind, table in (
            ("claim", "claims"),
            ("entity", "entities"),
            ("relation", "relations"),
        ):
            conn.execute(
                f"INSERT INTO {table}(brain_id,id,kind,status,payload_json) VALUES (?,?,'fact','active',?)",
                (b, kind, '{"text":"Reviewed evidence"}'),
            )
            conn.execute(
                "INSERT INTO dependencies VALUES (?,?,?,'source',?,?)",
                (b, kind, kind, source["id"], source["id"]),
            )
        conn.execute(
            "INSERT INTO claims(brain_id,id,kind,status,payload_json) VALUES (?,'untouched','fact','active',?)",
            (b, '{"text":"Other evidence"}'),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'claim','untouched','source',?,?)",
            (b, untouched["id"], untouched["id"]),
        )
        conn.execute(
            "INSERT INTO packets(brain_id,id,principal_id,revision,digest,payload_json) VALUES (?,'issued','owner',1,'digest',?)",
            (b, '{"text":"Issued evidence"}'),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'packet','issued','claim','claim',?)",
            (b, source["id"]),
        )
    if action == "access":
        s.set_source_access(
            principal=owner, brain_id=b, source_id=source["id"], readers=[]
        )
    elif action == "update":
        imported(s, owner, b, b"Changed basis", source_id=source["id"])
    else:
        s.change_source(
            principal=owner, brain_id=b, source_id=source["id"], action=action
        )
    with s.store.transaction() as conn:
        for table, record in (
            ("claims", "claim"),
            ("entities", "entity"),
            ("relations", "relation"),
        ):
            row = conn.execute(
                f"SELECT status,payload_json FROM {table} WHERE brain_id=? AND id=?",
                (b, record),
            ).fetchone()
            assert row["status"] == status
            expected = {} if action == "delete" else {"text": "Reviewed evidence"}
            if action == "update":
                expected["needs_recheck"] = True
            assert json.loads(row["payload_json"]) == expected
        packet = conn.execute(
            "SELECT status,payload_json FROM packets WHERE id='issued'"
        ).fetchone()
        assert packet["status"] == "revoked"
        assert json.loads(packet["payload_json"]) == (
            {} if action == "delete" else {"text": "Issued evidence"}
        )
        row = conn.execute(
            "SELECT status,payload_json FROM claims WHERE id='untouched'"
        ).fetchone()
        assert row[:] == ("active", '{"text":"Other evidence"}')


@pytest.mark.parametrize("kind", ["agent", "human"])
def test_import_only_principal_cannot_retry_creator_stored_content(
    context, tmp_path, kind
):
    s, owner, b = context
    p = preview(s, owner, b, b"Human reviewed source")
    first = commit(s, owner, b, p)
    restricted = Principal("owner", kind, {b}, {"import"})
    s.close()
    reopened = BrainService(tmp_path)
    try:
        with pytest.raises(BrainError) as exc:
            commit(reopened, restricted, b, p)
        assert exc.value.code == "not_found"
        allowed = Principal("owner", kind, {b}, {"import", "read"})
        assert commit(reopened, allowed, b, p) == first
    finally:
        reopened.close()


@pytest.mark.parametrize("existing", [False, True])
def test_import_commit_requires_read_for_new_and_existing_stored_citations(
    context, existing
):
    s, owner, b = context
    if existing:
        imported(s, owner, b)
    p = preview(s, owner, b)
    before = s.list_brains(principal=owner)[0]["revision"]
    restricted = Principal("owner", "agent", {b}, {"import"})
    with pytest.raises(BrainError) as exc:
        commit(s, restricted, b, p)
    assert exc.value.code == "not_found"
    assert s.list_brains(principal=owner)[0]["revision"] == before
    assert len(s.list_sources(principal=owner, brain_id=b)) == int(existing)
    assert (
        commit(s, owner, b, p)["sources"][0]["citations"][0]["text"]
        == "Ship on Friday."
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_import_preview_requires_read_before_returning_stored_source_identity(
    context, explicit
):
    s, owner, b = context
    source = imported(s, owner, b)
    restricted = Principal("owner", "agent", {b}, {"import"})
    with pytest.raises(BrainError) as exc:
        preview(s, restricted, b, **({"source_id": source["id"]} if explicit else {}))
    assert exc.value.code == "not_found"
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM previews WHERE status='pending'"
            ).fetchone()[0]
            == 0
        )


def test_import_only_can_preview_supplied_bytes_and_cancel_without_reading_stored_data(
    context,
):
    s, owner, b = context
    restricted = Principal("owner", "agent", {b}, {"import"})
    p = preview(s, restricted, b, b"Explicit supplied bytes")
    assert p["files"][0]["preview_text"] == "Explicit supplied bytes"
    args = dict(principal=restricted, brain_id=b, preview_id=p["id"], accepted_ids=[])
    assert s.commit_import(**args) == {"sources": []}
    assert s.commit_import(**args) == {"sources": []}
    assert s.list_sources(principal=owner, brain_id=b) == []
