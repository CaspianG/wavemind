from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from wavemind import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    HashingTextEncoder,
    SQLiteExperienceStore,
    TrustClass,
    WaveMind,
)
from wavemind.product_backup import (
    EXPERIENCE_NAME,
    ProductBackupError,
    create_product_backup,
    restore_product_backup,
)


def _verified_experience() -> ExperienceRecord:
    return ExperienceRecord.create(
        kind=ExperienceKind.FACT,
        title="Verified deployment preference",
        content="The operator requires a clean-install smoke before release.",
        source=ExperienceSource(
            provider="test",
            source_type="operator_verification",
            source_id="verification-1",
        ),
        namespace="tenant:a:release",
        confidence=1.0,
        trust=TrustClass.VERIFIED_OPERATOR,
        status=ExperienceStatus.ACTIVE,
    )


def test_product_backup_restores_core_and_verified_experience(tmp_path: Path) -> None:
    core_path = tmp_path / "core.sqlite3"
    experience_path = tmp_path / "experience.sqlite3"
    archive = tmp_path / "product.zip"
    mind = WaveMind(
        db_path=core_path,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        memory_id = mind.remember(
            "Andrey requires a clean release smoke",
            namespace="tenant:a:release",
        )
        with SQLiteExperienceStore(experience_path) as store:
            experience = store.put(_verified_experience())
            create_product_backup(mind, store, archive)
    finally:
        mind.close()

    restored_core = tmp_path / "restored" / "core.sqlite3"
    restored_experience = tmp_path / "restored" / "experience.sqlite3"
    restore_product_backup(
        archive,
        core_destination=restored_core,
        experience_destination=restored_experience,
    )

    restored_mind = WaveMind(
        db_path=restored_core,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        record = restored_mind.store.get(memory_id)
        assert record is not None
        assert record.namespace == "tenant:a:release"
    finally:
        restored_mind.close()
    with SQLiteExperienceStore(restored_experience) as restored_store:
        restored = restored_store.get(experience.id)
        assert restored is not None
        assert restored.trust is TrustClass.VERIFIED_OPERATOR
        assert restored.status is ExperienceStatus.ACTIVE


def test_product_restore_rejects_tampered_database(tmp_path: Path) -> None:
    archive = tmp_path / "product.zip"
    mind = WaveMind(
        db_path=tmp_path / "core.sqlite3",
        encoder=HashingTextEncoder(vector_dim=32),
    )
    try:
        with SQLiteExperienceStore(tmp_path / "experience.sqlite3") as store:
            create_product_backup(mind, store, archive)
    finally:
        mind.close()

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == EXPERIENCE_NAME:
                payload += b"tampered"
            target.writestr(name, payload)

    with pytest.raises(ProductBackupError, match="size mismatch"):
        restore_product_backup(
            tampered,
            core_destination=tmp_path / "out-core.sqlite3",
            experience_destination=tmp_path / "out-experience.sqlite3",
        )
