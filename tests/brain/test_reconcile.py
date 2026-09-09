"""Reviewed memory must preserve time, source authority, and explicit intent."""

import json

import pytest

from wavemind.brain.models import BrainError, Principal
from wavemind.brain.service import BrainService


@pytest.mark.parametrize(
    "parent_state", ["approved", "unreviewed", "stale", "conflicted"]
)
def test_context_conflict_opt_in_only_relaxes_root(source_fixture, parent_state):
    from wavemind.brain import reconcile

    s, owner, brain, cid = source_fixture
    propose(
        source_fixture,
        claim(cid, "parent", key="parent", valid_until=20),
        claim(cid, "a", depends_on=["parent"]),
        claim(cid, "b", "200", depends_on=["parent"]),
    )
    review(source_fixture, ["parent", "a", "b"])
    with s.store.transaction(write=True) as conn:
        if parent_state == "unreviewed":
            conn.execute(
                "UPDATE claims SET payload_json=json_set(payload_json,'$._review','none') WHERE brain_id=? AND id='parent'",
                (brain,),
            )
        elif parent_state == "stale":
            conn.execute(
                "UPDATE claims SET payload_json=json_set(payload_json,'$.needs_recheck',json('true')) WHERE brain_id=? AND id='parent'",
                (brain,),
            )
        elif parent_state == "conflicted":
            conn.execute(
                "UPDATE claims SET status='conflicted' WHERE brain_id=? AND id='parent'",
                (brain,),
            )
    with s.store.transaction() as conn:
        args = dict(
            principal=owner,
            brain_id=brain,
            record_type="claim",
            record_id="a",
            as_of=10,
        )
        assert reconcile.record_eligible(conn, **args) is False
        assert reconcile.context_record_state(conn, **args, conflict=True) == (
            parent_state == "approved",
            (20,),
        )
        assert reconcile.context_record_state(
            conn, **(args | {"as_of": 20}), conflict=True
        ) == (False, (20,))


def test_context_state_finishes_ineligible_prerequisite_walk(
    source_fixture, monkeypatch
):
    from wavemind.brain import reconcile

    s, owner, brain, cid = source_fixture
    propose(
        source_fixture,
        claim(cid, "parent", key="parent", valid_from=1100),
        claim(cid, "child", valid_from=2000, depends_on=["parent"]),
    )
    review(source_fixture, ["parent", "child"])
    args = dict(
        principal=owner,
        brain_id=brain,
        record_type="claim",
        record_id="child",
        as_of=1000,
    )
    with s.store.transaction() as conn:
        assert reconcile.context_record_state(conn, **args) == (False, (1100, 2000))
    monkeypatch.setattr(reconcile, "MAX_RECORDS", 1)
    with s.store.transaction() as conn:
        assert reconcile.record_eligible(conn, **args) is False
        with pytest.raises(BrainError) as error:
            reconcile.context_record_state(conn, **args)
        assert error.value.code == "dependency_limit"


def test_context_state_preserves_supersession_lineage_time_exception(source_fixture):
    from wavemind.brain import reconcile

    s, owner, brain, cid = source_fixture
    propose(
        source_fixture,
        claim(cid, "basis", key="basis", valid_from=5, valid_until=20),
        claim(cid, "a", valid_from=0, depends_on=["basis"]),
        claim(cid, "b", "200", valid_from=10, supersedes="a"),
    )
    review(source_fixture, ["basis", "a", "b"])
    with s.store.transaction() as conn:
        args = dict(
            principal=owner,
            brain_id=brain,
            record_type="claim",
            record_id="b",
            as_of=15,
        )
        assert reconcile.context_record_state(conn, **args) == (True, (5, 10, 20))
        assert reconcile.context_record_state(conn, **(args | {"as_of": 20})) == (
            False,
            (5, 10, 20),
        )


def import_source(s, owner, brain, content=b"Budget evidence", **fields):
    preview = s.preview_import(
        principal=owner,
        brain_id=brain,
        files=[dict(name="evidence.md", content=content, **fields)],
    )
    return s.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=preview["id"],
        accepted_ids=[preview["files"][0]["id"]],
    )["sources"][0]


@pytest.fixture
def source_fixture(tmp_path):
    s, owner = BrainService(tmp_path), Principal("owner")
    brain = s.create_brain(principal=owner, title="Memory")["id"]
    source = import_source(s, owner, brain)
    yield s, owner, brain, source["citations"][0]["id"]
    s.close()


def claim(citation, record_id="a", content="100", **fields):
    return (
        dict(
            id=record_id,
            kind="constraint",
            key="budget",
            content=content,
            citation_ids=[citation],
        )
        | fields
    )


def propose(fixture, *claims):
    s, owner, brain, _ = fixture
    return s.propose_claims(principal=owner, brain_id=brain, claims=list(claims))


def review(fixture, ids, action="approve"):
    s, owner, brain, _ = fixture
    return s.review_claims(
        principal=owner, brain_id=brain, claim_ids=ids, action=action
    )


def memory(fixture):
    s, owner, brain, _ = fixture
    return s.review_memory(principal=owner, brain_id=brain)


def test_competing_values_do_not_choose_latest_import(source_fixture):
    citation = source_fixture[3]
    rows = propose(source_fixture, claim(citation), claim(citation, "b", "200"))
    assert [r["status"] for r in rows] == ["proposed", "proposed"]
    review(source_fixture, ["a", "b"])
    assert {r["status"] for r in memory(source_fixture)["claims"]} == {"conflicted"}
    review(source_fixture, ["b"], "reject")
    rows = review(source_fixture, ["a"])
    assert rows[0]["status"] == "active"
    assert {r["id"]: r["status"] for r in memory(source_fixture)["claims"]} == {
        "a": "active",
        "b": "revoked",
    }


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_correction_arrival_order_preserves_half_open_history(
    source_fixture, tmp_path, order
):
    s, owner, brain, citation = source_fixture
    inputs = {
        "a": claim(citation, valid_from=0, event_time=900),
        "b": claim(
            citation,
            "b",
            "200",
            supersedes="a",
            valid_from=10,
            valid_until=20,
            event_time=1,
        ),
    }
    for record in order:
        propose(source_fixture, inputs[record])
        result = review(source_fixture, [record])[0]
        if record == "b" and order[0] == "b":
            assert result["status"] == "proposed"
    rows = {r["id"]: r for r in memory(source_fixture)["claims"]}
    assert rows["a"]["status"] == "superseded"
    assert (rows["a"]["effective_valid_from"], rows["a"]["effective_valid_until"]) == (
        0,
        10,
    )
    assert rows["a"]["valid_until"] is None
    assert rows["b"]["status"] == "active"
    assert (rows["b"]["effective_valid_from"], rows["b"]["effective_valid_until"]) == (
        10,
        20,
    )
    assert isinstance(rows["b"]["registered_at"], float)
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert reopened.review_memory(principal=owner, brain_id=brain)[
            "claims"
        ] == list(rows.values())
    finally:
        reopened.close()


def test_event_time_is_correction_start_when_explicit_bound_unknown(source_fixture):
    c = source_fixture[3]
    propose(
        source_fixture, claim(c), claim(c, "b", "200", supersedes="a", event_time=25)
    )
    review(source_fixture, ["a", "b"])
    rows = memory(source_fixture)["claims"]
    assert rows[0]["effective_valid_until"] == 25
    assert rows[1]["effective_valid_from"] == 25


def test_adjacent_intervals_and_equal_values_do_not_conflict(source_fixture):
    c = source_fixture[3]
    propose(
        source_fixture,
        claim(c, valid_until=10),
        claim(c, "b", "200", valid_from=10),
        claim(c, "c", "200", valid_from=10),
    )
    review(source_fixture, ["a", "b", "c"])
    assert [r["status"] for r in memory(source_fixture)["claims"]] == ["active"] * 3


def test_correction_forks_remain_conflicted_without_latest_winner(source_fixture):
    c = source_fixture[3]
    propose(
        source_fixture,
        claim(c),
        claim(c, "b", "200", supersedes="a", valid_from=10),
        claim(c, "c", "300", supersedes="a", valid_from=10),
    )
    review(source_fixture, ["a", "b", "c"])
    assert {r["id"]: r["status"] for r in memory(source_fixture)["claims"]} == {
        "a": "superseded",
        "b": "conflicted",
        "c": "conflicted",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"valid_from": float("nan")},
        {"valid_until": float("inf")},
        {"event_time": float("-inf")},
        {"valid_from": True},
        {"valid_from": 10, "valid_until": 10},
        {"valid_from": 10, "valid_until": 5},
        {"citation_ids": []},
        {"entity_ids": ["unknown"]},
        {"depends_on": ["unknown"]},
        {"kind": "causal_effect"},
        {"content": ""},
        {"content": "bad\ud800"},
        {"approved": True},
        {"id": "bad id"},
    ],
)
def test_invalid_claims_are_atomic_domain_failures(source_fixture, fields):
    c = source_fixture[3]
    invalid = claim(c, "b") | fields
    with pytest.raises(BrainError) as exc:
        propose(source_fixture, claim(c), invalid)
    assert exc.value.code in {"invalid_input", "not_found"}
    assert memory(source_fixture)["claims"] == []


def test_multiline_claims_preserve_exact_content(source_fixture):
    row = propose(
        source_fixture, claim(source_fixture[3], content="Budget:\n100\tEUR")
    )[0]
    assert row["content"] == "Budget:\n100\tEUR"


def test_unknown_original_does_not_activate_and_cycles_are_atomic(source_fixture):
    c = source_fixture[3]
    propose(source_fixture, claim(c, "b", "200", supersedes="a", valid_from=10))
    assert review(source_fixture, ["b"])[0]["status"] == "proposed"
    with pytest.raises(BrainError) as exc:
        propose(source_fixture, claim(c, supersedes="b", valid_from=20))
    assert exc.value.code == "invalid_input"
    assert [r["id"] for r in memory(source_fixture)["claims"]] == ["b"]


def test_foreign_citations_and_reference_targets_never_authorize_claim(source_fixture):
    s, owner, brain, citation = source_fixture
    other = s.create_brain(principal=owner, title="Other")["id"]
    foreign = import_source(s, owner, other, b"Foreign evidence")["citations"][0]["id"]
    entity = s.create_entity(
        principal=owner,
        brain_id=other,
        kind="project",
        name="Foreign",
        citation_ids=[foreign],
    )
    for fields in (
        {"citation_ids": [foreign]},
        {"entity_ids": [entity["id"]]},
        {"depends_on": [entity["id"]]},
    ):
        with pytest.raises(BrainError) as exc:
            propose(source_fixture, claim(citation) | fields)
        assert exc.value.code == "not_found"
    assert s.review_memory(principal=owner, brain_id=brain)["claims"] == []


@pytest.mark.parametrize("kind", ["human", "agent"])
def test_propose_and_review_independently_require_read(source_fixture, kind):
    s, owner, brain, citation = source_fixture
    restricted = Principal("owner", kind, {brain}, {"propose", "review"})
    with pytest.raises(BrainError) as exc:
        s.propose_claims(principal=restricted, brain_id=brain, claims=[claim(citation)])
    assert exc.value.code == "not_found"
    propose(source_fixture, claim(citation))
    with pytest.raises(BrainError) as exc:
        s.review_claims(
            principal=restricted, brain_id=brain, claim_ids=["a"], action="approve"
        )
    assert exc.value.code == "not_found"
    assert memory(source_fixture)["claims"][0]["status"] == "proposed"


def test_hidden_transitive_sources_filter_rows_and_changes(source_fixture):
    s, owner, brain, citation = source_fixture
    hidden = import_source(s, owner, brain, b"Hidden basis")
    s.set_member(principal=owner, brain_id=brain, identity="reader", role="reader")
    propose(source_fixture, claim(hidden["citations"][0]["id"], "secret"))
    propose(
        source_fixture,
        claim(citation, "derived", key="other") | {"depends_on": ["secret"]},
    )
    s.set_source_access(
        principal=owner, brain_id=brain, source_id=hidden["id"], readers=[]
    )
    view = s.review_memory(principal=Principal("reader"), brain_id=brain)
    assert view["claims"] == []
    assert view["changes"] == []
    assert view["pending"] == []


def test_entities_with_identical_names_are_explicitly_distinct(source_fixture):
    s, owner, brain, citation = source_fixture
    entities = [
        s.create_entity(
            principal=owner,
            brain_id=brain,
            kind="person",
            name="Alex",
            citation_ids=[citation],
        )
        for _ in range(2)
    ]
    assert entities[0]["id"] != entities[1]["id"]
    assert [e["status"] for e in entities] == ["proposed", "proposed"]
    assert [e["name"] for e in memory(source_fixture)["entities"]] == ["Alex", "Alex"]


def test_correction_without_effective_time_remains_explicitly_pending(source_fixture):
    c = source_fixture[3]
    propose(source_fixture, claim(c), claim(c, "b", "200", supersedes="a"))
    review(source_fixture, ["a", "b"])
    assert [r["status"] for r in memory(source_fixture)["claims"]] == [
        "active",
        "proposed",
    ]
    assert {
        "record_type": "claim",
        "id": "b",
        "reason": "needs_effective_time",
    } in memory(source_fixture)["pending"]


def test_rejected_fork_does_not_clip_predecessor(source_fixture):
    c = source_fixture[3]
    propose(
        source_fixture,
        claim(c, valid_from=100),
        claim(c, "b", "200", supersedes="a", valid_from=200),
        claim(c, "c", "300", supersedes="a", valid_from=210, valid_until=300),
    )
    review(source_fixture, ["a", "b", "c"])
    review(source_fixture, ["b"], "reject")
    review(source_fixture, ["c"])
    rows = {r["id"]: r for r in memory(source_fixture)["claims"]}
    assert (rows["a"]["effective_valid_from"], rows["a"]["effective_valid_until"]) == (
        100,
        210,
    )
    assert rows["c"]["effective_valid_until"] == 300


def test_owner_explicitly_reviews_entities_and_relations(source_fixture):
    s, owner, brain, c = source_fixture
    agent = Principal("owner", "agent", {brain}, {"read", "propose", "review"})
    entity = s.create_entity(
        principal=agent, brain_id=brain, kind="project", name="Plan", citation_ids=[c]
    )
    propose(source_fixture, claim(c))
    relation = s.add_relation(
        principal=agent,
        brain_id=brain,
        relation={
            "kind": "related_to",
            "from_id": entity["id"],
            "to_id": "a",
            "citation_ids": [c],
        },
    )
    assert relation["status"] == "proposed"
    with pytest.raises(BrainError) as exc:
        s.review_records(
            principal=agent,
            brain_id=brain,
            record_type="entity",
            record_ids=[entity["id"]],
            action="approve",
        )
    assert exc.value.code == "not_found"
    assert (
        s.review_records(
            principal=owner,
            brain_id=brain,
            record_type="entity",
            record_ids=[entity["id"]],
            action="approve",
        )[0]["status"]
        == "active"
    )
    review(source_fixture, ["a"])
    assert (
        s.review_records(
            principal=owner,
            brain_id=brain,
            record_type="relation",
            record_ids=[relation["id"]],
            action="approve",
        )[0]["status"]
        == "active"
    )


def test_review_batch_denial_rolls_back_and_duplicate_id_cannot_overwrite(
    source_fixture,
):
    propose(source_fixture, claim(source_fixture[3]))
    with pytest.raises(BrainError):
        review(source_fixture, ["a", "missing"])
    assert memory(source_fixture)["claims"][0]["status"] == "proposed"
    with pytest.raises(BrainError):
        propose(source_fixture, claim(source_fixture[3], content="overwritten"))
    assert memory(source_fixture)["claims"][0]["content"] == "100"


def test_source_update_requires_individual_owner_recheck_without_order_revival(
    source_fixture, tmp_path
):
    s, owner, brain, c = source_fixture
    second = import_source(s, owner, brain, b"Separate evidence")
    source_id = s.read_citation(principal=owner, brain_id=brain, citation_id=c)[
        "source_id"
    ]
    propose(
        source_fixture,
        claim(c),
        claim(second["citations"][0]["id"], "b", key="dependent", depends_on=["a"]),
    )
    review(source_fixture, ["a", "b"])
    import_source(s, owner, brain, b"Changed evidence", source_id=source_id)
    assert [r["status"] for r in memory(source_fixture)["claims"]] == [
        "proposed",
        "proposed",
    ]
    review(source_fixture, ["a", "b"])
    assert all(r["needs_recheck"] for r in memory(source_fixture)["claims"])
    assert [r["status"] for r in memory(source_fixture)["claims"]] == [
        "proposed",
        "proposed",
    ]
    review(source_fixture, ["a"], "recheck")
    assert [r["status"] for r in memory(source_fixture)["claims"]] == [
        "active",
        "proposed",
    ]
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert (
            reopened.review_memory(principal=owner, brain_id=brain)["claims"][1][
                "needs_recheck"
            ]
            is True
        )
        assert (
            reopened.review_claims(
                principal=owner, brain_id=brain, claim_ids=["b"], action="recheck"
            )[0]["status"]
            == "active"
        )
    finally:
        reopened.close()


def test_rejecting_dependency_invalidates_descendants_and_prevents_auto_reapproval(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c), claim(c, "b", key="dependent", depends_on=["a"]))
    review(source_fixture, ["a", "b"])
    with s.store.transaction(write=True) as conn:
        sid = conn.execute(
            "SELECT id FROM sources WHERE brain_id=?", (brain,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO packets(brain_id,id,principal_id,revision,digest) VALUES (?,'p','owner',1,'d')",
            (brain,),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'packet','p','claim','b',?)",
            (brain, sid),
        )
    review(source_fixture, ["a"], "reject")
    review(source_fixture, ["a"])
    rows = memory(source_fixture)["claims"]
    assert rows[0]["status"] == "active"
    assert rows[1]["status"] == "proposed" and rows[1]["needs_recheck"] is True
    with s.store.transaction() as conn:
        assert (
            conn.execute("SELECT status FROM packets WHERE id='p'").fetchone()[0]
            == "revoked"
        )


def test_changed_entity_and_relation_have_explicit_recheck_path(source_fixture):
    s, owner, brain, c = source_fixture
    entity = s.create_entity(
        principal=owner, brain_id=brain, kind="project", name="Alpha", citation_ids=[c]
    )
    s.review_records(
        principal=owner,
        brain_id=brain,
        record_type="entity",
        record_ids=[entity["id"]],
        action="approve",
    )
    propose(source_fixture, claim(c))
    review(source_fixture, ["a"])
    relation = s.add_relation(
        principal=owner,
        brain_id=brain,
        relation={
            "kind": "related_to",
            "from_id": "a",
            "to_id": entity["id"],
            "citation_ids": [c],
        },
    )
    s.review_records(
        principal=owner,
        brain_id=brain,
        record_type="relation",
        record_ids=[relation["id"]],
        action="approve",
    )
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    import_source(s, owner, brain, b"New entity evidence", source_id=sid)
    assert memory(source_fixture)["relations"][0]["status"] == "proposed"
    review(source_fixture, ["a"], "recheck")
    s.review_records(
        principal=owner,
        brain_id=brain,
        record_type="entity",
        record_ids=[entity["id"]],
        action="recheck",
    )
    assert (
        s.review_records(
            principal=owner,
            brain_id=brain,
            record_type="relation",
            record_ids=[relation["id"]],
            action="recheck",
        )[0]["status"]
        == "active"
    )


def test_correction_induced_history_requires_correction_source_visibility(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    secret = import_source(s, owner, brain, b"Hidden correction evidence")
    propose(
        source_fixture,
        claim(c),
        claim(secret["citations"][0]["id"], "b", "200", supersedes="a", valid_from=10),
    )
    review(source_fixture, ["a", "b"])
    s.set_member(principal=owner, brain_id=brain, identity="reader", role="reader")
    s.set_source_access(
        principal=owner, brain_id=brain, source_id=secret["id"], readers=[]
    )
    assert (
        s.review_memory(principal=Principal("reader"), brain_id=brain)["claims"] == []
    )


def test_dependencies_cycle_is_rejected_even_with_valid_evidence(source_fixture):
    c = source_fixture[3]
    with pytest.raises(BrainError) as exc:
        propose(
            source_fixture, claim(c, depends_on=["b"]), claim(c, "b", depends_on=["a"])
        )
    assert exc.value.code == "invalid_input"
    assert memory(source_fixture)["claims"] == []


def test_deleting_source_erases_all_transitive_derived_payloads(source_fixture):
    s, owner, brain, c = source_fixture
    other = import_source(s, owner, brain, b"Other evidence")
    entity = s.create_entity(
        principal=owner,
        brain_id=brain,
        kind="project",
        name="PRIVATE ENTITY",
        citation_ids=[c],
    )
    propose(
        source_fixture,
        claim(
            other["citations"][0]["id"],
            content="PRIVATE CLAIM",
            entity_ids=[entity["id"]],
        ),
    )
    relation = s.add_relation(
        principal=owner,
        brain_id=brain,
        relation={
            "kind": "related_to",
            "from_id": entity["id"],
            "to_id": "a",
            "citation_ids": [c],
        },
    )
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    with s.store.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO packets(brain_id,id,principal_id,revision,digest,payload_json) VALUES (?,'p','owner',1,'d',?)",
            (brain, '{"text":"PRIVATE PACKET"}'),
        )
        conn.execute(
            "INSERT INTO receipts(brain_id,id,packet_id,principal_id,packet_digest,payload_json) VALUES (?,'r','p','owner','d',?)",
            (brain, '{"text":"PRIVATE RECEIPT"}'),
        )
        conn.execute(
            "INSERT INTO outcomes(brain_id,id,receipt_id,payload_json) VALUES (?,'o','r',?)",
            (brain, '{"text":"PRIVATE OUTCOME"}'),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'packet','p','relation',?,?)",
            (brain, relation["id"], other["id"]),
        )
        conn.execute(
            "INSERT INTO outbox(brain_id,id,kind,source_id,payload_json) VALUES (?,'old','cleanup',?,?)",
            (brain, sid, '{"text":"PRIVATE OUTBOX"}'),
        )
    s.change_source(principal=owner, brain_id=brain, source_id=sid, action="delete")
    with s.store.transaction() as conn:
        for table in (
            "claims",
            "entities",
            "relations",
            "packets",
            "receipts",
            "outcomes",
            "outbox",
        ):
            assert all(
                "PRIVATE" not in r[0]
                for r in conn.execute(
                    f"SELECT payload_json FROM {table} WHERE brain_id=?", (brain,)
                )
            )
    assert memory(source_fixture)["claims"] == []


def test_closure_overflow_persists_and_owner_recovery_does_not_approve(
    source_fixture, tmp_path
):
    s, owner, brain, c = source_fixture
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    other = import_source(s, owner, brain, b"Independent evidence")
    propose(source_fixture, claim(other["citations"][0]["id"], "independent"))
    with s.store.transaction(write=True) as conn:
        conn.executemany(
            "INSERT INTO claims(brain_id,id,kind,status,payload_json) VALUES (?,?,'fact','active',?)",
            [(brain, f"bulk{i}", '{"content":"PRIVATE BULK"}') for i in range(10000)],
        )
        conn.executemany(
            "INSERT INTO dependencies VALUES (?,'claim',?,'source',?,?)",
            [(brain, f"bulk{i}", sid, sid) for i in range(10000)],
        )
    import_source(s, owner, brain, b"Updated oversized source", source_id=sid)
    from wavemind.brain.sources import context_pending

    with s.store.transaction() as conn:
        assert context_pending(conn, brain_id=brain) is True
    agent = Principal("owner", "agent", {brain}, {"read", "review"})
    with pytest.raises(BrainError):
        s.recheck_dependencies(principal=agent, brain_id=brain)
    assert s.recheck_dependencies(principal=owner, brain_id=brain) == {
        "pending": True,
        "reason": "dependency_limit",
    }
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert {
            "record_type": "brain",
            "id": brain,
            "reason": "dependency_limit",
        } in reopened.review_memory(principal=owner, brain_id=brain)["pending"]
        reopened.change_source(
            principal=owner, brain_id=brain, source_id=sid, action="delete"
        )
        assert reopened.recheck_dependencies(principal=owner, brain_id=brain) == {
            "pending": False,
            "reason": None,
        }
        view = reopened.review_memory(principal=owner, brain_id=brain)
        assert [(r["id"], r["status"]) for r in view["claims"]] == [
            ("independent", "proposed")
        ]
        with reopened.store.transaction() as conn:
            assert all(
                "PRIVATE" not in r[0]
                for r in conn.execute(
                    "SELECT payload_json FROM claims WHERE brain_id=?", (brain,)
                )
            )
    finally:
        reopened.close()


def test_erasure_cycle_terminates_without_cross_brain_or_unrelated_deletion(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    source = s.read_citation(principal=owner, brain_id=brain, citation_id=c)[
        "source_id"
    ]
    other_brain = s.create_brain(principal=owner, title="Other")["id"]
    other_source = import_source(s, owner, other_brain, b"Different")["id"]
    with s.store.transaction(write=True) as conn:
        for b, sid in ((brain, source), (other_brain, other_source)):
            for rid, parent in (("x", "y"), ("y", "x")):
                conn.execute(
                    "INSERT INTO claims(brain_id,id,kind,payload_json) VALUES (?,?,'fact',?)",
                    (b, rid, '{"content":"cycle text"}'),
                )
                conn.execute(
                    "INSERT INTO dependencies VALUES (?,'claim',?,'claim',?,?)",
                    (b, rid, parent, sid),
                )
    s.change_source(principal=owner, brain_id=brain, source_id=source, action="delete")
    with s.store.transaction() as conn:
        assert [
            r[0]
            for r in conn.execute(
                "SELECT payload_json FROM claims WHERE brain_id=?", (brain,)
            )
        ] == ["{}", "{}"]
        assert [
            r[0]
            for r in conn.execute(
                "SELECT payload_json FROM claims WHERE brain_id=?", (other_brain,)
            )
        ] == ['{"content":"cycle text"}'] * 2


def test_interrupted_erasure_rolls_back_and_returns_sanitized_error(
    source_fixture, monkeypatch
):
    from wavemind.brain import sources

    s, owner, brain, c = source_fixture
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    propose(source_fixture, claim(c, content="PRIVATE RETAINED"))
    monkeypatch.setattr(sources, "ERASURE_SECONDS", -1)
    with pytest.raises(BrainError) as exc:
        s.change_source(principal=owner, brain_id=brain, source_id=sid, action="delete")
    assert exc.value.code == "deletion_failed"
    assert "PRIVATE" not in str(exc.value)
    assert (
        s.read_citation(principal=owner, brain_id=brain, citation_id=c)["text"]
        == "Budget evidence"
    )
    assert memory(source_fixture)["claims"][0]["content"] == "PRIVATE RETAINED"
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM tombstones WHERE brain_id=?", (brain,)
            ).fetchone()[0]
            == 0
        )


def test_conflict_metadata_and_downstream_rows_require_all_competing_sources(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    hidden = import_source(s, owner, brain, b"Hidden competing evidence")
    propose(
        source_fixture,
        claim(c),
        claim(c, "derived", key="derived", depends_on=["a"]),
        claim(hidden["citations"][0]["id"], "b", "200"),
    )
    review(source_fixture, ["a", "derived"])
    review(source_fixture, ["b"])
    s.set_member(principal=owner, brain_id=brain, identity="reader", role="reader")
    s.set_source_access(
        principal=owner, brain_id=brain, source_id=hidden["id"], readers=[]
    )
    view = s.review_memory(principal=Principal("reader"), brain_id=brain)
    assert view["claims"] == [] and view["changes"] == []


def test_conflict_invalidates_previously_approved_descendant_until_recheck(
    source_fixture,
):
    c = source_fixture[3]
    propose(
        source_fixture,
        claim(c),
        claim(c, "dependent", key="dependent", depends_on=["a"]),
    )
    review(source_fixture, ["a", "dependent"])
    propose(source_fixture, claim(c, "b", "200"))
    review(source_fixture, ["b"])
    review(source_fixture, ["b"], "reject")
    review(source_fixture, ["a"])
    rows = {r["id"]: r for r in memory(source_fixture)["claims"]}
    assert rows["dependent"]["status"] == "proposed"
    assert rows["dependent"]["needs_recheck"] is True


def test_approved_corrected_predecessor_history_propagates_acl_to_descendants(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    hidden = import_source(s, owner, brain, b"Private correction")
    propose(
        source_fixture,
        claim(c),
        claim(c, "derived", key="other", depends_on=["a"]),
        claim(hidden["citations"][0]["id"], "b", "200", supersedes="a", valid_from=10),
    )
    review(source_fixture, ["a", "derived", "b"])
    s.set_member(principal=owner, brain_id=brain, identity="reader", role="reader")
    s.set_source_access(
        principal=owner, brain_id=brain, source_id=hidden["id"], readers=[]
    )
    assert (
        s.review_memory(principal=Principal("reader"), brain_id=brain)["claims"] == []
    )


def test_reviewing_descendant_first_cannot_consume_stale_dependency_recheck(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c), claim(c, "b", key="other", depends_on=["a"]))
    review(source_fixture, ["a", "b"])
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    import_source(s, owner, brain, b"Changed", source_id=sid)
    review(source_fixture, ["b"], "recheck")
    review(source_fixture, ["a"], "recheck")
    assert memory(source_fixture)["claims"][1]["status"] == "proposed"
    assert memory(source_fixture)["claims"][1]["needs_recheck"] is True


def test_sql_graph_cycles_cannot_be_cleared_by_recovery(source_fixture):
    from wavemind.brain.sources import mark_context_pending

    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c), claim(c, "b", key="other"))
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    with s.store.transaction(write=True) as conn:
        for rid, parent in (("a", "b"), ("b", "a")):
            conn.execute(
                "INSERT INTO dependencies VALUES (?,'claim',?,'claim',?,?)",
                (brain, rid, parent, sid),
            )
        mark_context_pending(conn, brain_id=brain)
    assert s.recheck_dependencies(principal=owner, brain_id=brain) == {
        "pending": True,
        "reason": "dependency_cycle",
    }


def test_schema_v1_migration_preserves_claim_data(source_fixture, tmp_path):
    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c))
    with s.store.transaction(write=True) as conn:
        conn.execute("DROP TABLE brain_context_state")
        conn.execute("PRAGMA user_version=1")
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert (
            reopened.review_memory(principal=owner, brain_id=brain)["claims"][0][
                "content"
            ]
            == "100"
        )
        with reopened.store.transaction() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"from_id": "missing"},
        {"to_id": "missing"},
        {"depends_on": ["missing"]},
        {"citation_ids": []},
        {"kind": "causes"},
        {"status": "active"},
    ],
)
def test_invalid_relations_never_persist(source_fixture, fields):
    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c), claim(c, "b"))
    with pytest.raises(BrainError):
        s.add_relation(
            principal=owner,
            brain_id=brain,
            relation={
                "kind": "related_to",
                "from_id": "a",
                "to_id": "b",
                "citation_ids": [c],
            }
            | fields,
        )
    assert memory(source_fixture)["relations"] == []


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_correction_before_original_start_has_explicit_empty_history(
    source_fixture, order
):
    c = source_fixture[3]
    inputs = {
        "a": claim(c, valid_from=100),
        "b": claim(c, "b", "200", supersedes="a", valid_from=50, valid_until=150),
    }
    for rid in order:
        propose(source_fixture, inputs[rid])
        review(source_fixture, [rid])
    rows = {r["id"]: r for r in memory(source_fixture)["claims"]}
    assert rows["a"]["status"] == "superseded"
    assert rows["a"]["effective_empty"] is True
    assert (rows["a"]["effective_valid_from"], rows["a"]["effective_valid_until"]) == (
        100,
        100,
    )
    assert rows["b"]["status"] == "active"


def test_as_of_eligibility_obeys_half_open_corrections_and_pending_gate(source_fixture):
    from wavemind.brain import reconcile
    from wavemind.brain.sources import mark_context_pending

    s, owner, brain, c = source_fixture
    propose(
        source_fixture,
        claim(c, valid_from=0),
        claim(c, "b", "200", supersedes="a", valid_from=10, valid_until=20),
    )
    review(source_fixture, ["a", "b"])
    with s.store.transaction() as conn:
        args = dict(principal=owner, brain_id=brain, record_type="claim")
        assert reconcile.record_eligible(conn, **args, record_id="a", as_of=9) is True
        assert reconcile.record_eligible(conn, **args, record_id="a", as_of=10) is False
        assert reconcile.record_eligible(conn, **args, record_id="b", as_of=10) is True
        assert reconcile.record_eligible(conn, **args, record_id="b", as_of=20) is False
        assert reconcile.record_eligible(conn, **args, record_id="a", as_of=20) is False
    with s.store.transaction(write=True) as conn:
        mark_context_pending(conn, brain_id=brain)
    with s.store.transaction() as conn:
        assert reconcile.record_eligible(conn, **args, record_id="b", as_of=15) is False


def test_recovery_checks_packet_receipt_cycles_too(source_fixture):
    from wavemind.brain.sources import mark_context_pending

    s, owner, brain, c = source_fixture
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    with s.store.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO packets(brain_id,id,principal_id,revision,digest) VALUES (?,'p','owner',1,'d')",
            (brain,),
        )
        conn.execute(
            "INSERT INTO receipts(brain_id,id,packet_id,principal_id,packet_digest) VALUES (?,'r','p','owner','d')",
            (brain,),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'packet','p','receipt','r',?)",
            (brain, sid),
        )
        mark_context_pending(conn, brain_id=brain)
    assert s.recheck_dependencies(principal=owner, brain_id=brain) == {
        "pending": True,
        "reason": "dependency_cycle",
    }


def test_nonfinite_huge_integer_time_is_a_domain_error(source_fixture):
    with pytest.raises(BrainError) as exc:
        propose(source_fixture, claim(source_fixture[3], valid_from=10**1000))
    assert exc.value.code == "invalid_input"


def test_updated_original_must_be_rechecked_before_correction_can_be_rechecked(
    source_fixture,
):
    s, owner, brain, c = source_fixture
    other = import_source(s, owner, brain, b"Correction basis")
    propose(
        source_fixture,
        claim(c),
        claim(other["citations"][0]["id"], "b", "200", supersedes="a", valid_from=10),
    )
    review(source_fixture, ["a", "b"])
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    import_source(s, owner, brain, b"Changed original", source_id=sid)
    review(source_fixture, ["b"], "recheck")
    assert memory(source_fixture)["claims"][1]["status"] == "proposed"
    review(source_fixture, ["a"], "recheck")
    assert memory(source_fixture)["claims"][1]["status"] == "proposed"
    review(source_fixture, ["b"], "recheck")
    assert memory(source_fixture)["claims"][1]["status"] == "active"


def test_capacity_rejection_cannot_store_partial_provenance(source_fixture):
    s, owner, brain, c = source_fixture
    with s.store.transaction(write=True) as conn:
        conn.executemany(
            "INSERT INTO claims(brain_id,id,kind,payload_json) VALUES (?,?,'fact',?)",
            [(brain, f"bulk{i}", '{"content":"existing"}') for i in range(10000)],
        )
        sid = conn.execute(
            "SELECT id FROM sources WHERE brain_id=?", (brain,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'claim','bulk0','source',?,?)",
            (brain, sid, sid),
        )
    with pytest.raises(BrainError) as exc:
        propose(source_fixture, claim(c, "overflow", depends_on=["bulk0"]))
    assert exc.value.code == "dependency_limit"
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM claims WHERE brain_id=? AND id='overflow'",
                (brain,),
            ).fetchone()[0]
            == 0
        )


def test_rejected_history_does_not_reopen_global_pending_on_future_review(
    source_fixture,
):
    from wavemind.brain.sources import context_pending

    s, owner, brain, c = source_fixture
    with s.store.transaction(write=True) as conn:
        conn.executemany(
            "INSERT INTO claims(brain_id,id,kind,status,payload_json) VALUES (?,?,'fact','revoked',?)",
            [
                (brain, f"history{i}", '{"content":"history","_review":"rejected"}')
                for i in range(10000)
            ],
        )
    propose(source_fixture, claim(c))
    assert review(source_fixture, ["a"])[0]["status"] == "active"
    with s.store.transaction() as conn:
        assert context_pending(conn, brain_id=brain) is False


@pytest.mark.parametrize("kind", ["PRIVATE KIND", "unknown", "Person"])
def test_entity_kind_is_exact_public_taxonomy_not_free_text(source_fixture, kind):
    s, owner, brain, c = source_fixture
    with pytest.raises(BrainError) as exc:
        s.create_entity(
            principal=owner, brain_id=brain, kind=kind, name="Alex", citation_ids=[c]
        )
    assert exc.value.code == "invalid_input"
    assert memory(source_fixture)["entities"] == []


@pytest.mark.parametrize(
    "kind", ["person", "organization", "project", "client", "artifact"]
)
def test_all_specified_entity_kinds_are_supported(source_fixture, kind):
    s, owner, brain, c = source_fixture
    row = s.create_entity(
        principal=owner, brain_id=brain, kind=kind, name="Name", citation_ids=[c]
    )
    assert row["kind"] == kind and row["status"] == "proposed"


@pytest.mark.parametrize(
    "record_type,table",
    [("entity", "entities"), ("claim", "claims"), ("relation", "relations")],
)
def test_deletion_scrubs_legacy_free_text_kind_column(
    source_fixture, record_type, table
):
    s, owner, brain, c = source_fixture
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    with s.store.transaction(write=True) as conn:
        conn.execute(
            f"INSERT INTO {table}(brain_id,id,kind,payload_json) VALUES (?,'legacy','PRIVATE KIND',?)",
            (brain, '{"content":"PRIVATE CONTENT"}'),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,?,'legacy','source',?,?)",
            (brain, record_type, sid, sid),
        )
    s.change_source(principal=owner, brain_id=brain, source_id=sid, action="delete")
    with s.store.transaction() as conn:
        assert conn.execute(
            f"SELECT kind,status,payload_json FROM {table} WHERE brain_id=? AND id='legacy'",
            (brain,),
        ).fetchone()[:] == ("deleted", "revoked", "{}")


def test_new_correction_cannot_bypass_original_required_recheck(
    source_fixture, tmp_path
):
    from wavemind.brain.reconcile import record_eligible

    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c, valid_from=0))
    review(source_fixture, ["a"])
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    import_source(s, owner, brain, b"Changed original", source_id=sid)
    independent = import_source(s, owner, brain, b"Correction evidence")
    propose(
        source_fixture,
        claim(
            independent["citations"][0]["id"], "b", "200", supersedes="a", valid_from=10
        ),
    )
    result = review(source_fixture, ["b"])[0]
    assert result["status"] == "proposed" and result["needs_recheck"] is True
    with s.store.transaction() as conn:
        assert (
            record_eligible(
                conn,
                principal=owner,
                brain_id=brain,
                record_type="claim",
                record_id="b",
                as_of=15,
            )
            is False
        )
    review(source_fixture, ["a"], "recheck")
    assert memory(source_fixture)["claims"][1]["status"] == "proposed"
    s.close()
    reopened = BrainService(tmp_path)
    try:
        assert (
            reopened.review_claims(
                principal=owner, brain_id=brain, claim_ids=["b"], action="recheck"
            )[0]["status"]
            == "active"
        )
        with reopened.store.transaction() as conn:
            # The predecessor's time has ended; this must not block its valid correction.
            assert (
                record_eligible(
                    conn,
                    principal=owner,
                    brain_id=brain,
                    record_type="claim",
                    record_id="a",
                    as_of=15,
                )
                is False
            )
            assert (
                record_eligible(
                    conn,
                    principal=owner,
                    brain_id=brain,
                    record_type="claim",
                    record_id="b",
                    as_of=15,
                )
                is True
            )
    finally:
        reopened.close()


@pytest.mark.parametrize("change", ["conflict", "correction", "rejected_fork"])
def test_reconciliation_basis_change_revokes_issued_packet_chain(
    source_fixture, tmp_path, change
):
    s, owner, brain, c = source_fixture
    propose(
        source_fixture, claim(c, valid_from=0), claim(c, "unrelated", key="unrelated")
    )
    review(source_fixture, ["a", "unrelated"])
    if change == "rejected_fork":
        propose(
            source_fixture,
            claim(c, "b", "200", supersedes="a", valid_from=10),
            claim(c, "fork", "300", supersedes="a", valid_from=20),
        )
        review(source_fixture, ["b", "fork"])
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    with s.store.transaction(write=True) as conn:
        for packet, origin in (("p", "a"), ("untouched", "unrelated")):
            conn.execute(
                "INSERT INTO packets(brain_id,id,principal_id,revision,digest,payload_json) VALUES (?,?,'owner',1,'digest',?)",
                (brain, packet, '{"text":"Issued context"}'),
            )
            conn.execute(
                "INSERT INTO dependencies VALUES (?,'packet',?,'claim',?,?)",
                (brain, packet, origin, sid),
            )
        conn.execute(
            "INSERT INTO receipts(brain_id,id,packet_id,principal_id,packet_digest) VALUES (?,'r','p','owner','digest')",
            (brain,),
        )
        conn.execute(
            "INSERT INTO outcomes(brain_id,id,receipt_id,status,payload_json) VALUES (?,'o','r','active',?)",
            (brain, '{"text":"Prior outcome"}'),
        )
        conn.execute(
            "INSERT INTO previews(brain_id,id,principal_id,payload_json) VALUES (?,'context-preview','owner',?)",
            (brain, '{"text":"Preview of original"}'),
        )
        conn.execute(
            "INSERT INTO dependencies VALUES (?,'preview','context-preview','claim','a',?)",
            (brain, sid),
        )
    if change == "rejected_fork":
        review(source_fixture, ["b"], "reject")
        assert memory(source_fixture)["claims"][0]["effective_valid_until"] == 20
    else:
        fields = {"supersedes": "a", "valid_from": 10} if change == "correction" else {}
        propose(source_fixture, claim(c, "b", "200", **fields))
        review(source_fixture, ["b"])
    with s.store.transaction() as conn:
        assert (
            conn.execute(
                "SELECT status FROM packets WHERE brain_id=? AND id='p'", (brain,)
            ).fetchone()[0]
            == "revoked"
        )
        assert (
            conn.execute(
                "SELECT status FROM outcomes WHERE brain_id=? AND id='o'", (brain,)
            ).fetchone()[0]
            == "revoked"
        )
        assert conn.execute(
            "SELECT status,payload_json FROM previews WHERE brain_id=? AND id='context-preview'",
            (brain,),
        ).fetchone()[:] == ("revoked", "{}")
        assert (
            conn.execute(
                "SELECT status FROM packets WHERE brain_id=? AND id='untouched'",
                (brain,),
            ).fetchone()[0]
            == "active"
        )
    if change == "correction":
        assert {r["id"]: r["status"] for r in memory(source_fixture)["claims"]}[
            "b"
        ] == "active"
    s.close()
    reopened = BrainService(tmp_path)
    try:
        with reopened.store.transaction() as conn:
            assert (
                conn.execute(
                    "SELECT status FROM packets WHERE brain_id=? AND id='p'", (brain,)
                ).fetchone()[0]
                == "revoked"
            )
    finally:
        reopened.close()


def test_as_of_dependency_expiry_applies_transitively_and_to_relation_endpoints(
    source_fixture,
):
    from wavemind.brain.reconcile import record_eligible

    s, owner, brain, c = source_fixture
    propose(
        source_fixture,
        claim(c, valid_from=0, valid_until=10),
        claim(c, "b", key="b", valid_from=0, valid_until=20, depends_on=["a"]),
        claim(c, "child", key="child", valid_from=0, valid_until=30, depends_on=["b"]),
    )
    review(source_fixture, ["a", "b", "child"])
    relation = s.add_relation(
        principal=owner,
        brain_id=brain,
        relation={
            "kind": "related_to",
            "from_id": "a",
            "to_id": "child",
            "citation_ids": [c],
        },
    )
    s.review_records(
        principal=owner,
        brain_id=brain,
        record_type="relation",
        record_ids=[relation["id"]],
        action="approve",
    )
    with s.store.transaction() as conn:
        for kind, rid in (
            ("claim", "a"),
            ("claim", "b"),
            ("claim", "child"),
            ("relation", relation["id"]),
        ):
            args = dict(
                principal=owner, brain_id=brain, record_type=kind, record_id=rid
            )
            assert record_eligible(conn, **args, as_of=5) is True
            assert record_eligible(conn, **args, as_of=10) is False
            assert record_eligible(conn, **args, as_of=15) is False


def test_supersession_temporal_exception_does_not_override_explicit_dependency(
    source_fixture,
):
    from wavemind.brain.reconcile import record_eligible

    s, owner, brain, c = source_fixture
    propose(
        source_fixture,
        claim(c, valid_from=0, valid_until=10),
        claim(
            c,
            "b",
            "200",
            supersedes="a",
            valid_from=10,
            valid_until=20,
            depends_on=["a"],
        ),
    )
    review(source_fixture, ["a", "b"])
    with s.store.transaction() as conn:
        assert (
            record_eligible(
                conn,
                principal=owner,
                brain_id=brain,
                record_type="claim",
                record_id="b",
                as_of=15,
            )
            is False
        )


@pytest.mark.parametrize("storage", ["payload", "dependency_links"])
def test_as_of_dependency_cycle_reports_failure_without_read_transaction_writes(
    source_fixture, storage
):
    from wavemind.brain.reconcile import record_eligible
    from wavemind.brain.sources import context_pending

    s, owner, brain, c = source_fixture
    propose(source_fixture, claim(c), claim(c, "b", key="b"))
    review(source_fixture, ["a", "b"])
    with s.store.transaction(write=True) as conn:
        for rid, parent in (("a", "b"), ("b", "a")):
            if storage == "payload":
                conn.execute(
                    "UPDATE claims SET payload_json=json_set(payload_json,'$.depends_on',json(?)) WHERE brain_id=? AND id=?",
                    (json.dumps([parent]), brain, rid),
                )
            else:
                sid = conn.execute(
                    "SELECT id FROM sources WHERE brain_id=?", (brain,)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO dependencies VALUES (?,'claim',?,'claim',?,?)",
                    (brain, rid, parent, sid),
                )
    before = s.list_brains(principal=owner)[0]["revision"]
    with s.store.transaction() as conn:
        with pytest.raises(BrainError) as exc:
            record_eligible(
                conn,
                principal=owner,
                brain_id=brain,
                record_type="claim",
                record_id="a",
                as_of=15,
            )
        assert exc.value.code == "dependency_cycle"
        assert (
            "a" not in exc.value.message.split()
            and "b" not in exc.value.message.split()
        )
        assert context_pending(conn, brain_id=brain) is False
    assert s.list_brains(principal=owner)[0]["revision"] == before


def test_correction_activation_requires_usable_original_review_state(source_fixture):
    s, owner, brain, c = source_fixture
    entity = s.create_entity(
        principal=owner, brain_id=brain, kind="artifact", name="Basis", citation_ids=[c]
    )
    propose(
        source_fixture,
        claim(c, entity_ids=[entity["id"]]),
        claim(c, "b", "200", supersedes="a", valid_from=10),
    )
    review(source_fixture, ["a", "b"])
    assert {r["id"]: r["status"] for r in memory(source_fixture)["claims"]} == {
        "a": "proposed",
        "b": "proposed",
    }


def test_as_of_dependency_limit_reports_failure_without_read_transaction_writes(
    source_fixture,
):
    from wavemind.brain.reconcile import record_eligible
    from wavemind.brain.sources import context_pending

    s, owner, brain, c = source_fixture
    sid = s.read_citation(principal=owner, brain_id=brain, citation_id=c)["source_id"]
    with s.store.transaction(write=True) as conn:
        conn.executemany(
            "INSERT INTO claims(brain_id,id,kind,status,payload_json) VALUES (?,?,'fact','active',?)",
            [
                (
                    brain,
                    f"chain{i}",
                    json.dumps(
                        {
                            "kind": "fact",
                            "key": "chain",
                            "content": "Basis",
                            "citation_ids": [c],
                            "_review": "approved",
                            "effective_valid_from": 0,
                            "effective_valid_until": 20,
                            "depends_on": [f"chain{i - 1}"] if i else [],
                        }
                    ),
                )
                for i in range(10001)
            ],
        )
        conn.executemany(
            "INSERT INTO dependencies VALUES (?,'claim',?,'source',?,?)",
            [(brain, f"chain{i}", sid, sid) for i in range(10001)],
        )
    before = s.list_brains(principal=owner)[0]["revision"]
    with s.store.transaction() as conn:
        args = dict(principal=owner, brain_id=brain, record_type="claim", as_of=15)
        assert record_eligible(conn, **args, record_id="chain9999") is True
        with pytest.raises(BrainError) as exc:
            record_eligible(conn, **args, record_id="chain10000")
        assert exc.value.code == "dependency_limit"
        assert "chain" not in str(exc.value) and "10000" not in str(exc.value)
        assert context_pending(conn, brain_id=brain) is False
    assert s.list_brains(principal=owner)[0]["revision"] == before
