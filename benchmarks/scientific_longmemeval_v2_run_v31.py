from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_DIGEST = "bc1f895bdf8bd30027bcc17f1c3a375099c8ee442681382c56ba57fa7580793b"
DATASET_REVISION = "f152293e235517d504809563c833d7190b8c713b"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backend = _load(
    "scientific_longmemeval_v2_backend",
    ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py",
)
runner = _load(
    "wavemind_scientific_longmemeval_v31_run_base",
    ROOT / "benchmarks" / "scientific_longmemeval_v2_run.py",
)
runner.PROTOCOL_DIGEST = PROTOCOL_DIGEST


def main(argv: list[str] | None = None) -> int:
    args = runner.parse_args(argv)
    marker = runner.run(args)
    marker["schema"] = "wavemind.longmemeval_v2_full_run_marker.v31"
    marker["dataset_revision"] = DATASET_REVISION
    marker["protocol_digest"] = PROTOCOL_DIGEST
    marker_path = args.output_root.resolve() / "full_run_marker.json"
    runner._write_json(marker_path, marker)
    print(json.dumps(marker, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
