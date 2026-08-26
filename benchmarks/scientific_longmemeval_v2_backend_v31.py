from __future__ import annotations

import hashlib
import importlib.util
import threading
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
    backend_class = _base_module().register_backend(
        official_repository=official_repository,
        candidate_repository=candidate_repository,
    )
    original_init = backend_class.__init__
    original_compile_once = backend_class._compile_once
    original_query = backend_class.query
    original_post_query_hook = backend_class.post_query_hook

    def synchronized_init(self, memory_params):
        original_init(self, memory_params)
        self._v31_compile_lock = threading.Lock()
        self._v31_query_lock = threading.Lock()
        self._v31_query_metadata = threading.local()

    def synchronized_compile_once(self):
        if self._compiled:
            return
        with self._v31_compile_lock:
            if self._compiled:
                return
            original_compile_once(self)

    def synchronized_query(self, query, query_image=None):
        with self._v31_query_lock:
            context = original_query(self, query, query_image=query_image)
            self._v31_query_metadata.value = dict(self._last_metadata or {})
            return context

    def thread_local_post_query_hook(
        self,
        *,
        query,
        query_image,
        memory_context,
    ):
        metadata = getattr(self._v31_query_metadata, "value", None)
        if metadata is None:
            return original_post_query_hook(
                self,
                query=query,
                query_image=query_image,
                memory_context=memory_context,
            )
        del self._v31_query_metadata.value
        return dict(metadata)

    backend_class.__init__ = synchronized_init
    backend_class._compile_once = synchronized_compile_once
    backend_class.query = synchronized_query
    backend_class.post_query_hook = thread_local_post_query_hook
    return backend_class


def registration_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(BASE_PATH.read_bytes())
    digest.update(Path(__file__).read_bytes())
    digest.update(OFFICIAL_REPOSITORY_SHA.encode("ascii"))
    digest.update(CANDIDATE_SOURCE_SHA.encode("ascii"))
    digest.update(MEMORY_TYPE.encode("ascii"))
    return digest.hexdigest()
