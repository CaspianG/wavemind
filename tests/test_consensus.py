import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import (
    ConsensusLeaseError,
    ConsensusQuorumError,
    ConsensusRevisionError,
    ControlPlaneConsensus,
    run_control_plane_consensus_profile,
)


def _consensus() -> ControlPlaneConsensus:
    return ControlPlaneConsensus(
        [
            {"id": "node-a", "address": "https://wm-a.internal", "zone": "zone-a"},
            {"id": "node-b", "address": "https://wm-b.internal", "zone": "zone-b"},
            {"id": "node-c", "address": "https://wm-c.internal", "zone": "zone-c"},
        ],
        lease_ttl_seconds=10,
    )


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "wavemind", *args],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def test_control_plane_consensus_commits_only_with_valid_majority_lease():
    consensus = _consensus()

    lease = consensus.acquire_leader_lease("node-a", now=100)
    result = consensus.commit_config_change(
        leader_id="node-a",
        change_type="autoscale",
        payload={"target_replicas": 5},
        expected_revision=0,
        now=101,
    )

    assert lease.term == 1
    assert lease.quorum_size == 3
    assert result.committed is True
    assert result.revision == 1
    assert result.term == 1
    assert consensus.config_revision == 1
    assert [entry.revision for entry in consensus.log] == [1]


def test_control_plane_consensus_blocks_stale_leader_and_stale_revision():
    consensus = _consensus()
    consensus.acquire_leader_lease("node-a", now=100)
    consensus.commit_config_change(
        leader_id="node-a",
        change_type="autoscale",
        payload={"target_replicas": 5},
        expected_revision=0,
        now=101,
    )

    with pytest.raises(ConsensusLeaseError):
        consensus.acquire_leader_lease("node-b", now=102)

    with pytest.raises(ConsensusRevisionError):
        consensus.commit_config_change(
            leader_id="node-a",
            change_type="autoscale",
            payload={"target_replicas": 6},
            expected_revision=0,
            now=103,
        )


def test_control_plane_consensus_blocks_minority_partition():
    consensus = _consensus()
    consensus.acquire_leader_lease("node-a", now=100)
    consensus.commit_config_change(
        leader_id="node-a",
        change_type="autoscale",
        payload={"target_replicas": 5},
        expected_revision=0,
        now=101,
    )
    consensus.set_node_available("node-b", False)
    consensus.set_node_available("node-c", False)

    with pytest.raises(ConsensusQuorumError):
        consensus.commit_config_change(
            leader_id="node-a",
            change_type="autoscale",
            payload={"target_replicas": 6},
            expected_revision=1,
            now=102,
        )

    assert consensus.config_revision == 1
    assert len(consensus.log) == 1


def test_control_plane_consensus_rotates_leader_after_lease_expiry_and_membership_change():
    consensus = _consensus()
    consensus.acquire_leader_lease("node-a", now=100)
    consensus.commit_config_change(
        leader_id="node-a",
        change_type="autoscale",
        payload={"target_replicas": 5},
        expected_revision=0,
        now=101,
    )

    next_lease = consensus.acquire_leader_lease("node-b", now=111)
    membership = consensus.commit_config_change(
        leader_id="node-b",
        change_type="membership",
        payload={
            "nodes": [
                {"id": "node-a", "address": "https://wm-a.internal", "zone": "zone-a"},
                {"id": "node-b", "address": "https://wm-b.internal", "zone": "zone-b"},
                {"id": "node-c", "address": "https://wm-c.internal", "zone": "zone-c"},
                {"id": "node-d", "address": "https://wm-d.internal", "zone": "zone-d"},
                {"id": "node-e", "address": "https://wm-e.internal", "zone": "zone-e"},
            ]
        },
        expected_revision=1,
        now=112,
    )

    assert next_lease.term == 2
    assert membership.revision == 2
    assert consensus.majority == 3
    assert consensus.voter_ids == ("node-a", "node-b", "node-c", "node-d", "node-e")
    assert consensus.as_dict()["config_revision"] == 2


def test_control_plane_consensus_profile_is_release_gate_ready():
    payload = run_control_plane_consensus_profile()

    assert payload["ok"] is True
    assert payload["stale_leader_blocked"] is True
    assert payload["stale_revision_blocked"] is True
    assert payload["minority_commit_blocked"] is True
    assert payload["membership_committed"] is True
    assert payload["monotonic_terms"] is True
    assert payload["monotonic_revisions"] is True


def test_control_plane_consensus_profile_uses_supplied_cluster_nodes():
    payload = run_control_plane_consensus_profile(
        [
            {"id": "wm-0", "address": "http://wm-0.internal"},
            {"id": "wm-1", "address": "http://wm-1.internal"},
            {"id": "wm-2", "address": "http://wm-2.internal"},
            {"id": "wm-3", "address": "http://wm-3.internal"},
        ],
        lease_ttl_seconds=15,
        config_revision=7,
    )

    assert payload["ok"] is True
    assert payload["voters_initial"] == 4
    assert payload["voters_after_membership"] == 4
    assert payload["majority_initial"] == 3
    assert payload["majority_after_membership"] == 3
    assert payload["first_revision"] == 8
    assert payload["final_revision"] == 9
    assert payload["minority_commit_blocked"] is True


def test_control_plane_consensus_profile_rejects_tiny_cluster_for_production():
    payload = run_control_plane_consensus_profile(["wm-0", "wm-1"])

    assert payload["ok"] is False
    assert payload["voters_initial"] == 2
    assert "at least three voters" in payload["error"]


def test_cli_control_plane_consensus_outputs_json():
    result = run_cli("control-plane-consensus", "--json")
    payload = json.loads(result.stdout)

    assert payload["engine"] == "WaveMind control-plane consensus"
    assert payload["ok"] is True
    assert payload["final_revision"] == 2
