from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


GENESIS_HASH = "0" * 64
LEDGER_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class LedgerIntegrity:
    status: str
    records: int
    legacy_records: int
    hashed_records: int
    anchored_legacy_records: int
    tip_hash: str


def canonical_record(record: Mapping[str, Any]) -> bytes:
    payload = dict(record)
    payload.pop("record_hash", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def chained_record_hash(previous_hash: str, record: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(str(previous_hash).encode("ascii"))
    digest.update(b"\n")
    digest.update(canonical_record(record))
    return digest.hexdigest()


def verify_ledger_rows(rows: Iterable[Mapping[str, Any]]) -> LedgerIntegrity:
    selected = [dict(row) for row in rows]
    previous_hash = GENESIS_HASH
    legacy_records = 0
    hashed_records = 0
    hash_chain_started = False
    seen_ids: set[str] = set()

    for index, row in enumerate(selected, start=1):
        forecast_id = str(row.get("forecast_id", "")).strip()
        if not forecast_id:
            raise ValueError(f"Missing forecast_id at ledger record {index}")
        if forecast_id in seen_ids:
            raise ValueError(f"Duplicate forecast_id at ledger record {index}: {forecast_id}")
        seen_ids.add(forecast_id)

        has_integrity = any(
            key in row
            for key in (
                "ledger_schema_version",
                "previous_record_hash",
                "record_hash",
            )
        )
        if not has_integrity:
            if hash_chain_started:
                raise ValueError(
                    f"Legacy ledger record {index} appears after the hash chain started"
                )
            legacy_records += 1
            previous_hash = chained_record_hash(previous_hash, row)
            continue

        hash_chain_started = True
        schema_version = int(row.get("ledger_schema_version", 0))
        if schema_version != LEDGER_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported ledger_schema_version at record {index}: {schema_version}"
            )
        recorded_previous = str(row.get("previous_record_hash", ""))
        if recorded_previous != previous_hash:
            raise ValueError(
                f"Ledger chain mismatch at record {index}: previous_record_hash is invalid"
            )
        expected_hash = chained_record_hash(previous_hash, row)
        if str(row.get("record_hash", "")) != expected_hash:
            raise ValueError(f"Ledger chain mismatch at record {index}: record_hash is invalid")
        hashed_records += 1
        previous_hash = expected_hash

    status = "verified" if hashed_records else "legacy_unanchored"
    return LedgerIntegrity(
        status=status,
        records=len(selected),
        legacy_records=legacy_records,
        hashed_records=hashed_records,
        anchored_legacy_records=legacy_records if hashed_records else 0,
        tip_hash=previous_hash,
    )


def read_ledger(path: str | Path) -> tuple[list[dict[str, Any]], LedgerIntegrity]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        raise FileNotFoundError(f"Forecast ledger does not exist: {ledger_path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        ledger_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {ledger_path}:{line_number}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Ledger record must be an object at {ledger_path}:{line_number}")
        rows.append(dict(payload))
    return rows, verify_ledger_rows(rows)


def seal_record(record: Mapping[str, Any], *, previous_hash: str) -> dict[str, Any]:
    sealed = dict(record)
    sealed["ledger_schema_version"] = LEDGER_SCHEMA_VERSION
    sealed["previous_record_hash"] = str(previous_hash)
    sealed.pop("record_hash", None)
    sealed["record_hash"] = chained_record_hash(previous_hash, sealed)
    return sealed
