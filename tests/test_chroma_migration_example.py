import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import WaveMind


pytest.importorskip("chromadb")


def load_example():
    path = Path("examples/chroma_migration.py")
    spec = importlib.util.spec_from_file_location("chroma_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chroma_migration_fixture_preserves_memory_shape(tmp_path):
    module = load_example()
    chroma_path = tmp_path / "chroma"
    wavemind_db = tmp_path / "wavemind.sqlite3"

    module.build_demo_chroma_collection(chroma_path)
    migrated = module.migrate_collection(
        chroma_path=chroma_path,
        wavemind_db_path=wavemind_db,
    )

    assert migrated == 4
    memory = WaveMind(db_path=wavemind_db)

    style_hits = memory.query(
        "answer style",
        namespace="user:42",
        tags=["preference"],
        top_k=3,
    )
    assert style_hits
    assert style_hits[0].text == "Andrey prefers short practical answers."
    assert style_hits[0].metadata["source"] == "chroma"
    assert style_hits[0].metadata["chroma_collection"] == module.DEFAULT_COLLECTION
    assert style_hits[0].metadata["chroma_id"] == "m2"
    assert set(style_hits[0].tags) >= {"preference", "style", "agent"}

    budget_hits = memory.query(
        "monthly budget",
        namespace="user:42",
        tags=["billing"],
        top_k=1,
    )
    assert budget_hits[0].metadata["chroma_id"] == "m3"

    isolated_hits = memory.query(
        "Andrey trader",
        namespace="user:7",
        top_k=3,
    )
    assert isolated_hits
    assert all("Andrey" not in hit.text for hit in isolated_hits)


def test_chroma_migration_example_runs_from_checkout(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    chroma_path = tmp_path / "chroma"
    wavemind_db = tmp_path / "wavemind.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            "examples/chroma_migration.py",
            "--chroma-path",
            str(chroma_path),
            "--wavemind-db",
            str(wavemind_db),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    assert "Migrated 4 Chroma records into WaveMind." in result.stdout
    assert "Andrey prefers short practical answers. [m2]" in result.stdout
