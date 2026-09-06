from __future__ import annotations

import hashlib
import importlib.util
import sys
import threading
import types
from pathlib import Path

from benchmarks.scientific_frozen_lexical_index import FrozenLexicalIndex


ROOT = Path(__file__).resolve().parents[1]
V31_PATH = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
OFFICIAL_REPOSITORY_SHA = "2cc8c540bdb87fe6761629b585e727e1c4704520"
CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
MEMORY_TYPE = "wavemind_scientific_indexed_prototype"
EVIDENCE_CLASS = "synthetic-performance-prototype-not-admission"


def _v31_module():
    spec = importlib.util.spec_from_file_location(
        "wavemind_scientific_longmemeval_indexed_v31_base",
        V31_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen v31 LongMemEval adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MEMORY_TYPE = MEMORY_TYPE
    return module


def register_backend(*, official_repository: str | Path, candidate_repository: str | Path):
    backend_class = _v31_module().register_backend(
        official_repository=official_repository,
        candidate_repository=candidate_repository,
    )
    original_init = backend_class.__init__
    original_compile_once = backend_class._compile_once
    original_query = backend_class.query
    original_close = backend_class.close

    def indexed_init(self, memory_params):
        original_init(self, memory_params)
        self._indexed_compile_lock = threading.Lock()
        self._indexed_ready = False
        self._frozen_lexical_index = None
        self._frozen_definitions = None

    def indexed_compile_once(self):
        if self._indexed_ready:
            return
        with self._indexed_compile_lock:
            if self._indexed_ready:
                return
            original_compile_once(self)
            definitions = self._runtime.event_log.definitions()
            index = FrozenLexicalIndex(
                self._work_dir / "frozen-lexical-index.sqlite3",
                definitions,
            )
            reconciler = self._runtime.state_reconciler

            def indexed_operation(
                reconciler_self,
                query,
                current_definitions,
                *,
                token_budget,
                latency_budget_ms,
            ):
                return index.select_operation_memories(
                    reconciler_self,
                    query,
                    current_definitions,
                    token_budget=token_budget,
                    latency_budget_ms=latency_budget_ms,
                )

            def indexed_ranked(
                reconciler_self,
                query,
                current_definitions,
                *,
                token_budget,
                latency_budget_ms,
            ):
                return index.select_ranked_memories(
                    reconciler_self,
                    query,
                    current_definitions,
                    token_budget=token_budget,
                    latency_budget_ms=latency_budget_ms,
                )

            reconciler._select_operation_memories = types.MethodType(
                indexed_operation,
                reconciler,
            )
            reconciler._select_ranked_memories = types.MethodType(
                indexed_ranked,
                reconciler,
            )

            def frozen_definitions(_event_log):
                return definitions

            self._runtime.event_log.definitions = types.MethodType(
                frozen_definitions,
                self._runtime.event_log,
            )
            self._frozen_definitions = definitions
            self._frozen_lexical_index = index
            self._indexed_ready = True

    def indexed_query(self, query, query_image=None):
        indexed_compile_once(self)
        return original_query(self, query, query_image=query_image)

    def indexed_close(self):
        index = self._frozen_lexical_index
        if index is not None:
            index.close()
            self._frozen_lexical_index = None
        original_close(self)

    backend_class.__init__ = indexed_init
    backend_class._compile_once = indexed_compile_once
    backend_class.query = indexed_query
    backend_class.close = indexed_close
    return backend_class


def registration_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(V31_PATH.read_bytes())
    digest.update(
        (ROOT / "benchmarks" / "scientific_frozen_lexical_index.py").read_bytes()
    )
    digest.update(Path(__file__).read_bytes())
    digest.update(OFFICIAL_REPOSITORY_SHA.encode("ascii"))
    digest.update(CANDIDATE_SOURCE_SHA.encode("ascii"))
    digest.update(MEMORY_TYPE.encode("ascii"))
    digest.update(EVIDENCE_CLASS.encode("ascii"))
    return digest.hexdigest()
