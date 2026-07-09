from __future__ import annotations

from collections import defaultdict
from typing import Any

from wavemind.active_active_drill import (
    parse_active_active_regions,
    run_active_active_drill,
)
from wavemind.cli import build_parser, main
from wavemind.core import QueryResult


class _ActiveActiveClient:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        self.tombstones: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.versions: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.failed_addresses: set[str] = set()
        self.next_id = 1

    def _check(self, address: str) -> None:
        if address in self.failed_addresses:
            raise RuntimeError(f"region network unavailable: {address}")

    def _changed(self, address: str, namespace: str) -> None:
        self.versions[address][namespace] += 1

    def stats(self, address: str) -> dict[str, Any]:
        self._check(address)
        return {"active_memories": sum(len(value) for value in self.records[address].values())}

    def remember(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        tags: tuple[str, ...] = (),
        **_: Any,
    ) -> int:
        self._check(address)
        record_id = self.next_id
        self.next_id += 1
        self.records[address][namespace][text] = {
            "id": record_id,
            "text": text,
            "namespace": namespace,
            "tags": list(tags),
            "metadata": {},
            "priority": 1.0,
        }
        self.tombstones[address][namespace].discard(text)
        self._changed(address, namespace)
        return record_id

    def forget(
        self,
        address: str,
        *,
        namespace: str,
        text: str,
        **_: Any,
    ) -> int:
        self._check(address)
        deleted = int(text in self.records[address][namespace])
        self.records[address][namespace].pop(text, None)
        self.tombstones[address][namespace].add(text)
        self._changed(address, namespace)
        return deleted

    def query(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        **_: Any,
    ) -> list[QueryResult]:
        self._check(address)
        record = self.records[address][namespace].get(text)
        if record is None or text in self.tombstones[address][namespace]:
            return []
        return [
            QueryResult(
                id=int(record["id"]),
                text=text,
                score=1.0,
                vector_score=1.0,
                field_score=0.0,
                graph_score=0.0,
                namespace=namespace,
                tags=tuple(record.get("tags") or ()),
                metadata={},
            )
        ]

    def export_namespace_delta(
        self,
        address: str,
        *,
        namespace: str,
        since: float | None,
        **_: Any,
    ) -> dict[str, Any]:
        self._check(address)
        version = self.versions[address][namespace]
        changed = since is None or float(since) < float(version)
        return {
            "records": (
                list(self.records[address][namespace].values()) if changed else []
            ),
            "tombstones": (
                [{"texts": [text], "record_keys": []} for text in self.tombstones[address][namespace]]
                if changed
                else []
            ),
            "cursor": float(version),
            "has_more": False,
            "field_state": {},
        }

    def import_namespace_delta(
        self,
        address: str,
        *,
        delta: dict[str, Any],
        namespace: str,
    ) -> dict[str, Any]:
        self._check(address)
        imported_records = 0
        skipped_records = 0
        imported_tombstones = 0
        deleted_records = 0
        changed = False
        for tombstone in delta.get("tombstones") or []:
            for text in tombstone.get("texts") or []:
                if text not in self.tombstones[address][namespace]:
                    self.tombstones[address][namespace].add(text)
                    imported_tombstones += 1
                    changed = True
                if text in self.records[address][namespace]:
                    self.records[address][namespace].pop(text, None)
                    deleted_records += 1
                    changed = True
        for record in delta.get("records") or []:
            text = str(record["text"])
            if text in self.tombstones[address][namespace]:
                skipped_records += 1
                continue
            if text in self.records[address][namespace]:
                skipped_records += 1
                continue
            self.records[address][namespace][text] = dict(record)
            imported_records += 1
            changed = True
        if changed:
            self._changed(address, namespace)
        return {
            "imported_records": imported_records,
            "skipped_records": skipped_records,
            "deleted_records": deleted_records,
            "imported_tombstones": imported_tombstones,
            "failed_nodes": {},
        }


def _regions() -> dict[str, str]:
    return {
        "region-a": "http://region-a.cluster.local:8000",
        "region-b": "http://region-b.cluster.local:8000",
        "region-c": "http://region-c.cluster.local:8000",
    }


def test_active_active_drill_converges_through_region_outage_and_recovery():
    client = _ActiveActiveClient()
    regions = _regions()
    common = {
        "namespace_prefix": "region-failure",
        "namespace_count": 3,
        "min_convergence_rate": 1.0,
    }

    seed = run_active_active_drill(regions, client=client, mode="seed", **common)
    client.failed_addresses.add(regions["region-b"])
    outage = run_active_active_drill(
        regions,
        client=client,
        mode="outage",
        failed_region="region-b",
        **common,
    )
    client.failed_addresses.clear()
    recovered = run_active_active_drill(
        regions,
        client=client,
        mode="recover",
        failed_region="region-b",
        **common,
    )

    assert seed["status"] == "pass"
    assert seed["writes"] == 9
    assert seed["verification"]["convergence_rate"] == 1.0
    assert outage["status"] == "pass"
    assert outage["unavailable_regions"] == ["region-b"]
    assert outage["surviving_regions"] == ["region-a", "region-c"]
    assert outage["writes"] == 6
    assert outage["verification"]["convergence_rate"] == 1.0
    assert outage["verification"]["delete_suppression_rate"] == 1.0
    assert recovered["status"] == "pass"
    assert recovered["unavailable_regions"] == []
    assert recovered["verification"]["convergence_rate"] == 1.0
    assert recovered["verification"]["delete_suppression_rate"] == 1.0
    assert recovered["sync"]["final_noop_records_imported"] == 0
    assert recovered["sync"]["final_noop_tombstones_imported"] == 0


def test_active_active_drill_requires_physical_expected_region_failure():
    payload = run_active_active_drill(
        _regions(),
        client=_ActiveActiveClient(),
        mode="outage",
        failed_region="region-b",
        namespace_count=1,
    )

    assert payload["status"] == "fail"
    assert "was not physically unavailable" in payload["error"]


def test_active_active_drill_cli_contract_and_parser(capsys):
    regions = parse_active_active_regions(
        [
            "region-a=http://region-a:8000",
            "region-b=http://region-b:8000",
            "region-c=http://region-c:8000",
        ]
    )
    assert list(regions) == ["region-a", "region-b", "region-c"]

    args = build_parser().parse_args(
        [
            "active-active-drill",
            "--mode",
            "recover",
            "--failed-region",
            "region-b",
            "--region",
            "region-a=http://region-a:8000",
            "--region",
            "region-b=http://region-b:8000",
            "--region",
            "region-c=http://region-c:8000",
        ]
    )
    assert args.command == "active-active-drill"
    assert args.namespace_count == 16

    exit_code = main(
        [
            "active-active-drill",
            "--mode",
            "seed",
            "--region",
            "only=http://only:8000",
        ]
    )
    assert exit_code == 2
    assert "at least three regions" in capsys.readouterr().err
