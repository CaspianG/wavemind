"""Build/validate a small standard-format companion without optional Jupyter deps."""

import argparse
import contextlib
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(path):
    sections = [
        ("markdown", "## tl;dr\nOfficial locally supplied data were profiled after a frozen header-only amendment. Full replay and 336 independent pandas checks pass. Baseline admission is false: actual human terms review and leakage-safe evaluation semantics remain pending. No model training or scoring is represented here."),
        ("markdown", "## Context & Methods\nFrozen protocol: workflow_intake_protocol.json. Source selection: PUBLIC_WORKFLOW_SELECTION.md.\n\n### Key Assumptions\nKeep all raw records unchanged. Split by normalized SMS group or whole incident, independently of labels. Do not infer chronology or field availability from enriched records. This is a read-only companion, not a downloader."),
        ("code", "import json\nfrom pathlib import Path\nplaces = [Path.cwd(), *Path.cwd().parents]\nhere = next(p for root in places for p in (root, root / 'research/breakthrough') if (p / 'workflow_intake_protocol.json').is_file())\nprotocol = json.loads((here / 'workflow_intake_protocol.json').read_text())\nprint(json.dumps({'phase': protocol['phase'], 'split': protocol['split']['partitions'], 'network_policy': protocol['network_policy']}, indent=2))"),
        ("markdown", "## Data\nOfficial dataset pages and DOI records are listed below. Archive hashes and local custody are recorded in the preserved run. Controller-supplied provenance is not independent authentication of the download. Raw messages and person identifiers are never displayed."),
        ("code", "for lane, config in protocol['lanes'].items():\n    print(lane, config['source_page'], config['doi'], config['documented_license'])"),
        ("markdown", "## Results\nInspect the fixed v2 receipt and verify its hash against the independent QA receipt. This notebook does not recreate the full raw-data audit; use the replay commands in WORKFLOW_INTAKE_V2_RESULTS.md for that. It does not create or repair a dataset."),
        ("code", "import hashlib\nrun_directory = here / 'runs/workflow_intake_v2'\nblob = (run_directory / 'result.json').read_bytes()\nresult = json.loads(blob)\nqa = json.loads((run_directory / 'independent_qa.json').read_text())\nassert hashlib.sha256(blob).hexdigest() == qa['checked_result_sha256']\nassert result['baseline_admitted'] is False\nassert result['training_runs'] == result['scoring_runs'] == 0\nprint(json.dumps({lane: {'status': info['status'], 'rows': info['profile']['rows'], 'split_sha256': info['split_sha256']} for lane, info in result['lanes'].items()}, indent=2))\nprint(json.dumps({'qa_checks': qa['checks_passed'], 'partitions': qa['partition_rows'], 'human_terms_review': result['human_terms_review']}, indent=2))\nsms = result['lanes']['sms']['profile']\ninc = result['lanes']['incidents']['profile']\nprint(json.dumps({'sms_cross_partition_templates': sms['digit_template_cross_partition_groups'], 'sms_affected_rows': sms['digit_template_cross_partition_rows'], 'incident_future_outcome_values': inc['future_outcome_values'], 'incident_regressions': inc['within_incident_file_order_regressions']}, indent=2))"),
        ("markdown", "## Takeaways\nSMS template overlap (4 groups / 12 rows) blocks semantic-generalization scoring until a leakage-safe subset is frozen. Incident enrichment is not proof of event-time observability; preserve missingness and chronology anomalies. Actual human review of both source-page terms and SMS README is pending. Neither software checks nor this intake establish scientific novelty or product utility. See WORKFLOW_INTAKE_V2_RESULTS.md for denominators and remediation, and R8_NEXT_GATE_BRIEF.md for the separate scientific handoff.\n\nExecution limitation: standard Python sequential code-cell replay only; no Jupyter kernel/nbclient execution is claimed."),
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
