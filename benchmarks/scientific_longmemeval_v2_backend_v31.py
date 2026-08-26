from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend.py"
OFFICIAL_REPOSITORY_SHA = "2cc8c540bdb87fe6761629b585e727e1c4704520"
CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
MEMORY_TYPE = "wavemind_scientific_v31"


def _base_module():
    spec = importlib.util.spec_from_file_location(
        "wavemind_scientific_longmemeval_v31_base", BASE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen LongMemEval-V2 adapter base")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OFFICIAL_REPOSITORY_SHA = OFFICIAL_REPOSITORY_SHA
    module.CANDIDATE_SOURCE_SHA = CANDIDATE_SOURCE_SHA
    module.MEMORY_TYPE = MEMORY_TYPE
    return module


def register_backend(*, official_repository: str | Path, candidate_repository: str | Path):
    return _base_module().register_backend(
        official_repository=official_repository,
        candidate_repository=candidate_repository,
    )


def registration_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(BASE_PATH.read_bytes())
    digest.update(Path(__file__).read_bytes())
    digest.update(OFFICIAL_REPOSITORY_SHA.encode("ascii"))
    digest.update(CANDIDATE_SOURCE_SHA.encode("ascii"))
    digest.update(MEMORY_TYPE.encode("ascii"))
    return digest.hexdigest()
