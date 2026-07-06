from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .cluster import ClusterNode


class ConsensusError(RuntimeError):
    """Base class for control-plane consensus failures."""


class ConsensusQuorumError(ConsensusError):
    """Raised when a majority of voters is unavailable."""


class ConsensusLeaseError(ConsensusError):
    """Raised when a node does not hold a valid leadership lease."""


class ConsensusRevisionError(ConsensusError):
    """Raised when a config change is based on a stale revision."""


@dataclass(frozen=True)
class LeaderLease:
    leader_id: str
    term: int
    lease_until: float
    acks: tuple[str, ...]

    @property
    def quorum_size(self) -> int:
        return len(self.acks)

    def is_valid(self, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current < self.lease_until

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["acks"] = list(self.acks)
        payload["valid"] = self.is_valid()
        return payload


@dataclass(frozen=True)
class ControlPlaneLogEntry:
    revision: int
    term: int
    leader_id: str
    change_type: str
    payload: dict[str, Any]
    acks: tuple[str, ...]
    committed_at: float

    def as_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "term": self.term,
            "leader_id": self.leader_id,
            "change_type": self.change_type,
            "payload": dict(self.payload),
            "acks": list(self.acks),
            "committed_at": self.committed_at,
        }


@dataclass(frozen=True)
class ConsensusCommitResult:
    committed: bool
    revision: int
    term: int
    leader_id: str
    change_type: str
    acks: tuple[str, ...]
    failed_nodes: dict[str, str] = field(default_factory=dict)

    @property
    def quorum_size(self) -> int:
        return len(self.acks)

    def as_dict(self) -> dict[str, object]:
        return {
            "committed": self.committed,
            "revision": self.revision,
            "term": self.term,
            "leader_id": self.leader_id,
            "change_type": self.change_type,
            "acks": list(self.acks),
            "failed_nodes": dict(self.failed_nodes),
            "quorum_size": self.quorum_size,
        }


class ControlPlaneConsensus:
    """Majority-based control-plane guard for cluster config changes.

    This is intentionally small and deterministic. It is not a full replicated
    Raft log implementation; it provides the safety checks WaveMind needs before
    applying cluster membership, sharding, or operator config changes:

    - only a node with a current majority leadership lease can commit;
    - every commit advances a monotonic config revision;
    - stale leaders and stale expected revisions are rejected;
    - minority partitions cannot elect a leader or commit config changes.
    """

    def __init__(
        self,
        nodes: Iterable[ClusterNode | dict[str, object] | str],
        *,
        lease_ttl_seconds: float = 30.0,
        term: int = 0,
        config_revision: int = 0,
    ) -> None:
        node_list = tuple(_coerce_node(node) for node in nodes)
        if not node_list:
            raise ValueError("At least one consensus voter is required")
        node_ids = [node.id for node in node_list]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("Consensus voter ids must be unique")
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        if term < 0:
            raise ValueError("term must be non-negative")
        if config_revision < 0:
            raise ValueError("config_revision must be non-negative")

        self.nodes = node_list
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.term = int(term)
        self.config_revision = int(config_revision)
        self._available = {node.id: True for node in node_list}
        self._lease: LeaderLease | None = None
        self._log: list[ControlPlaneLogEntry] = []

    @property
    def majority(self) -> int:
        return len(self.nodes) // 2 + 1

    @property
    def voter_ids(self) -> tuple[str, ...]:
        return tuple(node.id for node in self.nodes)

    @property
    def log(self) -> tuple[ControlPlaneLogEntry, ...]:
        return tuple(self._log)

    def set_node_available(self, node_id: str, available: bool) -> None:
        if node_id not in self._available:
            raise ValueError(f"Unknown consensus voter: {node_id}")
        self._available[node_id] = bool(available)

    def acquire_leader_lease(
        self,
        candidate_id: str,
        *,
        now: float | None = None,
    ) -> LeaderLease:
        self._require_known_voter(candidate_id)
        timestamp = _now(now)
        current = self._lease
        if current and current.is_valid(timestamp) and current.leader_id != candidate_id:
            raise ConsensusLeaseError(
                f"Leader lease is held by {current.leader_id!r} until {current.lease_until}"
            )
        acks = self._available_voters()
        if candidate_id not in acks:
            raise ConsensusQuorumError(f"Candidate {candidate_id!r} is unavailable")
        if len(acks) < self.majority:
            raise ConsensusQuorumError(
                f"Majority {self.majority} cannot be reached; available voters: {acks}"
            )
        self.term += 1
        lease = LeaderLease(
            leader_id=candidate_id,
            term=self.term,
            lease_until=timestamp + self.lease_ttl_seconds,
            acks=acks,
        )
        self._lease = lease
        return lease

    def commit_config_change(
        self,
        *,
        leader_id: str,
        change_type: str,
        payload: dict[str, Any],
        expected_revision: int | None = None,
        now: float | None = None,
    ) -> ConsensusCommitResult:
        self._require_known_voter(leader_id)
        if not change_type.strip():
            raise ValueError("change_type must not be empty")
        timestamp = _now(now)
        lease = self._lease
        if lease is None or lease.leader_id != leader_id or not lease.is_valid(timestamp):
            raise ConsensusLeaseError(f"{leader_id!r} does not hold a valid leader lease")
        if expected_revision is not None and int(expected_revision) != self.config_revision:
            raise ConsensusRevisionError(
                f"Expected revision {expected_revision}, current revision {self.config_revision}"
            )
        acks = self._available_voters()
        if leader_id not in acks:
            raise ConsensusQuorumError(f"Leader {leader_id!r} is unavailable")
        if len(acks) < self.majority:
            raise ConsensusQuorumError(
                f"Majority {self.majority} cannot be reached; available voters: {acks}"
            )

        self.config_revision += 1
        entry = ControlPlaneLogEntry(
            revision=self.config_revision,
            term=lease.term,
            leader_id=leader_id,
            change_type=change_type,
            payload=dict(payload),
            acks=acks,
            committed_at=timestamp,
        )
        self._log.append(entry)

        if change_type == "membership":
            self._apply_membership_payload(payload)

        return ConsensusCommitResult(
            committed=True,
            revision=entry.revision,
            term=entry.term,
            leader_id=leader_id,
            change_type=change_type,
            acks=acks,
        )

    def as_dict(self) -> dict[str, object]:
        lease = self._lease
        return {
            "voters": [node.as_dict() for node in self.nodes],
            "voter_count": len(self.nodes),
            "majority": self.majority,
            "term": self.term,
            "config_revision": self.config_revision,
            "available_voters": list(self._available_voters()),
            "leader_lease": lease.as_dict() if lease else None,
            "log": [entry.as_dict() for entry in self._log],
        }

    def _available_voters(self) -> tuple[str, ...]:
        return tuple(node.id for node in self.nodes if self._available.get(node.id, False))

    def _require_known_voter(self, node_id: str) -> None:
        if node_id not in self._available:
            raise ValueError(f"Unknown consensus voter: {node_id}")

    def _apply_membership_payload(self, payload: dict[str, Any]) -> None:
        raw_nodes = payload.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError("membership payload requires a non-empty nodes list")
        next_nodes = tuple(_coerce_node(node) for node in raw_nodes)
        node_ids = [node.id for node in next_nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("membership payload voter ids must be unique")
        previous_availability = dict(self._available)
        self.nodes = next_nodes
        self._available = {
            node.id: previous_availability.get(node.id, True)
            for node in next_nodes
        }
        if self._lease and self._lease.leader_id not in self._available:
            self._lease = None


def run_control_plane_consensus_profile() -> dict[str, object]:
    """Run a deterministic consensus safety profile for readiness gates."""

    consensus = ControlPlaneConsensus(
        [
            {"id": "node-a", "address": "https://wm-a.internal", "zone": "zone-a"},
            {"id": "node-b", "address": "https://wm-b.internal", "zone": "zone-b"},
            {"id": "node-c", "address": "https://wm-c.internal", "zone": "zone-c"},
        ],
        lease_ttl_seconds=10.0,
    )
    lease = consensus.acquire_leader_lease("node-a", now=100.0)
    first = consensus.commit_config_change(
        leader_id="node-a",
        change_type="autoscale",
        payload={"target_replicas": 5},
        expected_revision=0,
        now=101.0,
    )

    stale_leader_blocked = False
    try:
        consensus.acquire_leader_lease("node-b", now=102.0)
    except ConsensusLeaseError:
        stale_leader_blocked = True

    stale_revision_blocked = False
    try:
        consensus.commit_config_change(
            leader_id="node-a",
            change_type="autoscale",
            payload={"target_replicas": 6},
            expected_revision=0,
            now=103.0,
        )
    except ConsensusRevisionError:
        stale_revision_blocked = True

    consensus.set_node_available("node-b", False)
    consensus.set_node_available("node-c", False)
    minority_blocked = False
    try:
        consensus.commit_config_change(
            leader_id="node-a",
            change_type="autoscale",
            payload={"target_replicas": 7},
            expected_revision=1,
            now=104.0,
        )
    except ConsensusQuorumError:
        minority_blocked = True

    consensus.set_node_available("node-b", True)
    consensus.set_node_available("node-c", True)
    new_lease = consensus.acquire_leader_lease("node-b", now=111.0)
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
        now=112.0,
    )

    return {
        "engine": "WaveMind control-plane consensus",
        "voters_initial": 3,
        "voters_after_membership": len(consensus.nodes),
        "majority_initial": 2,
        "majority_after_membership": consensus.majority,
        "lease_term": lease.term,
        "new_leader_term": new_lease.term,
        "first_revision": first.revision,
        "final_revision": consensus.config_revision,
        "log_entries": len(consensus.log),
        "stale_leader_blocked": stale_leader_blocked,
        "stale_revision_blocked": stale_revision_blocked,
        "minority_commit_blocked": minority_blocked,
        "membership_committed": membership.committed,
        "membership_ack_count": membership.quorum_size,
        "monotonic_terms": new_lease.term > lease.term,
        "monotonic_revisions": [entry.revision for entry in consensus.log] == [1, 2],
        "ok": (
            first.committed
            and membership.committed
            and stale_leader_blocked
            and stale_revision_blocked
            and minority_blocked
            and new_lease.term > lease.term
            and [entry.revision for entry in consensus.log] == [1, 2]
        ),
    }


def _coerce_node(node: ClusterNode | dict[str, object] | str) -> ClusterNode:
    if isinstance(node, ClusterNode):
        return node
    if isinstance(node, str):
        return ClusterNode(id=node, address=node)
    return ClusterNode(
        id=str(node["id"]),
        address=str(node.get("address", node["id"])),
        zone=str(node["zone"]) if node.get("zone") is not None else None,
        weight=float(node.get("weight", 1.0)),
    )


def _now(value: float | None) -> float:
    return time.time() if value is None else float(value)
