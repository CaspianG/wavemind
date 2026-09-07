"""Build/validate a small standard-format companion without optional Jupyter deps."""

import argparse
import contextlib
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(path):
    sections = [
        ("markdown", "## tl;dr\nReal-data intake has not run: UCI access was denied. Parser unit tests are not dataset findings. No model training or scoring is represented here."),
        ("markdown", "## Context & Methods\nFrozen protocol: workflow_intake_protocol.json. Source selection: PUBLIC_WORKFLOW_SELECTION.md.\n\n### Key Assumptions\nKeep all raw records unchanged. Split by normalized SMS group or whole incident, independently of labels. Do not infer chronology or field availability from enriched records. This is a read-only companion, not a downloader."),
        ("code", "import json\nfrom pathlib import Path\nplaces = [Path.cwd(), *Path.cwd().parents]\nhere = next(p for root in places for p in (root, root / 'research/breakthrough') if (p / 'workflow_intake_protocol.json').is_file())\nprotocol = json.loads((here / 'workflow_intake_protocol.json').read_text())\nprint(json.dumps({'phase': protocol['phase'], 'split': protocol['split']['partitions'], 'network_policy': protocol['network_policy']}, indent=2))"),
        ("markdown", "## Data\nOfficial dataset pages and DOI records are listed below. These are documented sources, not proof that their archives were downloaded. Raw messages and person identifiers are never displayed."),
        ("code", "for lane, config in protocol['lanes'].items():\n    print(lane, config['source_page'], config['doi'], config['documented_license'])"),
        ("markdown", "## Results\nDisplay the saved intake status. To inspect a future real intake, set `run_directory` to its explicitly recorded output directory. This notebook does not create or repair a dataset."),
        ("code", "run_directory = None\nstatus_path = here / 'workflow_intake_status.json'\nstatus = json.loads(status_path.read_text()) if status_path.exists() else {'status': 'not_executed', 'reason': 'status record not yet preserved'}\nprint(json.dumps(status, indent=2))\nif run_directory is not None:\n    result = json.loads((Path(run_directory) / 'result.json').read_text())\n    print(json.dumps({lane: {'status': info['status'], 'rows': info.get('profile', {}).get('rows'), 'split_sha256': info.get('split_sha256')} for lane, info in result['lanes'].items()}, indent=2))"),
        ("markdown", "## Takeaways\nDo not infer usefulness, leakage-free evaluation or baseline readiness from a passing unit test. Authorized official archive intake and terms review remain prerequisites. Run only separately preregistered baselines after the quality audit. R8 scientific handoff is in R8_NEXT_GATE_BRIEF.md."),
    ]
    cells = []
    for index, (kind, source) in enumerate(sections):
        cell = {"id": f"intake-{index}", "cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)
    notebook = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                              "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(notebook, indent=2) + "\n")


def replay(path):
    notebook = json.loads(path.read_text())
    assert notebook["nbformat"] == 4 and notebook["nbformat_minor"] == 5
    assert len({cell["id"] for cell in notebook["cells"]}) == len(notebook["cells"])
    namespace, count = {}, 0
    for cell in notebook["cells"]:
        assert cell["cell_type"] in ("code", "markdown") and isinstance(cell["source"], list)
        if cell["cell_type"] == "code":
            count += 1
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                exec(compile("".join(cell["source"]), str(path), "exec"), namespace)
            cell["execution_count"] = count
            cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": capture.getvalue().splitlines(keepends=True)}]
    notebook["metadata"]["validation"] = {"method": "standard_python_sequential_cell_replay",
                                             "code_cells": count, "jupyter_kernel_execution": False}
    path.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")
    return {"code_cells_replayed": count, "jupyter_kernel_execution": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-existing", action="store_true")
    args = parser.parse_args()
    if not args.replay_existing:
        build(args.output)
    print(json.dumps(replay(args.output)))
