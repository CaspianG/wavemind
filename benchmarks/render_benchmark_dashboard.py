from __future__ import annotations

import argparse
import json
import html
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.render_benchmark_leaderboard import render_leaderboard, load_matrix


def _table_lines(markdown: str, header: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        return []
    output: list[str] = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        output.append(line)
    return output


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _markdown_table_to_html(lines: list[str], *, compact: bool = False) -> str:
    if len(lines) < 2:
        return ""
    headers = _split_row(lines[0])
    rows = [
        _split_row(line)
        for line in lines[2:]
        if line.startswith("|") and "---" not in line
    ]
    table_class = "compact" if compact else ""
    parts = [f'<table class="{table_class}">', "<thead><tr>"]
    parts.extend(f"<th>{html.escape(header)}</th>" for header in headers)
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for index, cell in enumerate(row):
            parts.append(f"<td>{_cell_html(cell, column=index)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def _cell_html(cell: str, *, column: int) -> str:
    safe = _markdown_links_to_html(cell).replace("`", "")
    if column == 5 or column == 2:
        lower = cell.lower()
        if "action required" in lower or "miss" in lower or "slower" in lower:
            return f'<span class="badge warn">{safe}</span>'
        if "pass" in lower or "leads" in lower or "faster" in lower:
            return f'<span class="badge pass">{safe}</span>'
    return safe


def _markdown_links_to_html(text: str) -> str:
    parts: list[str] = []
    position = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        parts.append(html.escape(text[position:match.start()]))
        label = html.escape(match.group(1))
        url = html.escape(match.group(2), quote=True)
        parts.append(f'<a href="{url}">{label}</a>')
        position = match.end()
    parts.append(html.escape(text[position:]))
    return "".join(parts)


def _metric_card(title: str, value: Any, detail: str) -> str:
    return (
        '<section class="metric-card">'
        f"<h2>{html.escape(title)}</h2>"
        f"<strong>{html.escape(str(value))}</strong>"
        f"<p>{html.escape(detail)}</p>"
        "</section>"
    )


def _summary_cards(payload: dict[str, Any]) -> str:
    benchmarks = payload.get("benchmarks", [])
    implemented = sum(1 for entry in benchmarks if entry.get("status") == "implemented")
    runner_ready = sum(1 for entry in benchmarks if entry.get("status") == "runner-ready")
    planned = sum(1 for entry in benchmarks if entry.get("status") == "planned")
    readiness = next(
        (
            entry
            for entry in benchmarks
            if entry.get("id") == "production_readiness_gate"
        ),
        {},
    )
    readiness_current = readiness.get("current", {}) if isinstance(readiness, dict) else {}
    readiness_metrics = {}
    if isinstance(readiness_current, dict):
        readiness_metrics = readiness_current.get("WaveMind production readiness", {}) or {}
    return "\n".join(
        [
            _metric_card(
                "Readiness",
                readiness_metrics.get("overall_status", "unknown"),
                f"{readiness_metrics.get('pass_count', '?')}/{readiness_metrics.get('total_criteria', '?')} criteria pass",
            ),
            _metric_card(
                "Implemented",
                implemented,
                f"{runner_ready} runner-ready and {planned} planned public proof paths",
            ),
            _metric_card(
                "Refresh",
                payload.get("generated_at", "unknown"),
                f"source {payload.get('source_ref', 'unknown')}",
            ),
        ]
    )


def _load_leaderboard_status(root: Path) -> dict[str, Any]:
    path = root / "docs" / "data" / "leaderboard-status.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _publication_contract_panel(status: dict[str, Any]) -> str:
    contract = status.get("publication_contract", {})
    checks = contract.get("checks", {}) if isinstance(contract, dict) else {}
    rows = [
        ("Status", contract.get("status", "missing")),
        ("Weekly schedule", contract.get("schedule_cron", "missing")),
        ("Refresh profile", contract.get("refresh_profile", "missing")),
        ("Pages URL", contract.get("public_url", "missing")),
        ("Source ref", contract.get("source_ref", "missing")),
        ("Workflow run", contract.get("workflow_run_id") or "local or manual artifact"),
    ]
    table = ["<table class=\"compact\"><tbody>"]
    for label, value in rows:
        table.append(
            "<tr>"
            f"<th>{html.escape(str(label))}</th>"
            f"<td>{html.escape(str(value))}</td>"
            "</tr>"
        )
    table.append("</tbody></table>")
    check_items = []
    for key, value in checks.items():
        label = key.replace("_", " ")
        css = "pass" if value else "warn"
        check_items.append(
            f'<span class="badge {css}">{html.escape(label)}: {str(bool(value)).lower()}</span>'
        )
    return (
        '<section class="panel">'
        "<h2>Publication Contract</h2>"
        "<p>The leaderboard is generated from artifacts, freshness-checked, "
        "published to GitHub Pages, and claim-limited until strict production evidence passes.</p>"
        '<div class="publication-grid">'
        f"<div>{''.join(table)}</div>"
        f"<div class=\"check-list\">{''.join(check_items)}</div>"
        "</div>"
        "</section>"
    )


def _agent_impact_panel(status: dict[str, Any]) -> str:
    impact = status.get("agent_impact", {}) if isinstance(status, dict) else {}
    if not isinstance(impact, dict) or not impact:
        return ""
    rows = [
        ("Status", impact.get("status", "missing")),
        ("Benchmarks", impact.get("benchmark_count", 0)),
        ("WaveMind wins", impact.get("wavemind_primary_wins", 0)),
        ("Average lift", _fmt_metric(impact.get("average_primary_lift"))),
        ("Context saved", _fmt_metric(impact.get("average_context_saved"))),
        ("Stale safety", _fmt_metric(impact.get("average_stale_safety_score"))),
        ("Best profile", impact.get("best_impact_profile", "missing")),
    ]
    table = ["<table class=\"compact\"><tbody>"]
    for label, value in rows:
        table.append(
            "<tr>"
            f"<th>{html.escape(str(label))}</th>"
            f"<td>{html.escape(str(value))}</td>"
            "</tr>"
        )
    table.append("</tbody></table>")
    return (
        '<section class="panel">'
        "<h2>Agent Impact</h2>"
        "<p>Behavioral evidence: task success, stale-fact suppression, context savings, "
        "long-memory retrieval, and checked-in answer-quality smoke results.</p>"
        f"{''.join(table)}"
        '<p><a href="../benchmarks/AGENT_IMPACT.md">Read the agent impact report</a></p>'
        "</section>"
    )


def _fmt_metric(value: Any) -> str:
    try:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def render_dashboard(root: Path = PROJECT_ROOT) -> str:
    payload = load_matrix(root)
    status = _load_leaderboard_status(root)
    leaderboard = render_leaderboard(root)
    benchmark_table = _markdown_table_to_html(
        _table_lines(
            leaderboard,
            "| benchmark | category | primary metric | best WaveMind result | best baseline result | readout |",
        )
    )
    evidence_table = _markdown_table_to_html(
        _table_lines(
            leaderboard,
            "| area | current source | claim status | next action |",
        ),
        compact=True,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WaveMind Living Benchmark Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #111827;
      --muted: #566174;
      --line: #d9e1ee;
      --pass: #0a7f5a;
      --warn: #9a5b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 24px 48px; }}
    header {{ margin-bottom: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(2rem, 5vw, 4.2rem); line-height: 0.98; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 1.1rem; }}
    p {{ margin: 0; color: var(--muted); }}
    a {{ color: #245bdb; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }}
    .metric-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }}
    .metric-card strong {{ display: block; margin-bottom: 6px; font-size: 1.9rem; }}
    .summary {{ width: 100%; max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e8edf5; text-align: left; vertical-align: top; }}
    th {{ background: #f1f4f9; font-weight: 700; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: 0; }}
    table.compact td {{ font-size: 0.86rem; }}
    .badge {{ display: inline-block; padding: 3px 7px; border-radius: 999px; background: #eef2f7; color: var(--text); }}
    .badge.pass {{ background: #e8f6ef; color: var(--pass); }}
    .badge.warn {{ background: #fff3dd; color: var(--warn); }}
    .section-title {{ margin: 30px 0 12px; }}
    .rules {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .rules p {{ padding: 12px; background: #fff; border: 1px solid var(--line); border-radius: 8px; }}
    .publication-grid {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 14px; align-items: start; }}
    .check-list {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    footer {{ margin-top: 30px; color: var(--muted); font-size: 0.9rem; }}
    @media (max-width: 760px) {{
      main {{ padding: 22px 14px 36px; }}
      .cards, .rules, .publication-grid {{ grid-template-columns: 1fr; }}
      th, td {{ padding: 9px 10px; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>WaveMind Living Benchmark Dashboard</h1>
    <p>Generated from checked-in benchmark artifacts. Planned rows are not claimed wins; external service evidence is shown separately.</p>
  </header>

  <div class="cards">
    {_summary_cards(payload)}
  </div>

  <section class="panel">
    <h2>Visual Summary</h2>
    <img class="summary" src="assets/benchmark-summary.svg" alt="WaveMind benchmark summary">
  </section>

  {_publication_contract_panel(status)}

  {_agent_impact_panel(status)}

  <h2 class="section-title">Benchmark Leaderboard</h2>
  <div class="table-wrap">
    {benchmark_table}
  </div>

  <h2 class="section-title">Evidence Source Status</h2>
  <div class="table-wrap">
    {evidence_table}
  </div>

  <h2 class="section-title">Reading Rules</h2>
  <div class="rules">
    <p>Quality wins and latency wins are separate. A row can lead on recall while still being slower.</p>
    <p>WaveMind-only rows are regression and capacity checks, not competitor claims.</p>
    <p>Production SLO rows use checked recall, p99, QPS, replica count, autoscaling, and cost assumptions.</p>
    <p>Remote active-active, managed serverless, and live competitor rows stay marked as external evidence until real service artifacts are checked in.</p>
  </div>

  <footer>
    Source: <code>benchmarks/benchmark_matrix_results.json</code>.
    Machine status: <a href="data/leaderboard-status.json">data/leaderboard-status.json</a>.
    Markdown view: <a href="../benchmarks/BENCHMARK_LEADERBOARD.md">benchmarks/BENCHMARK_LEADERBOARD.md</a>.
    Strict production evidence: <a href="../benchmarks/PRODUCTION_EVIDENCE.md">benchmarks/PRODUCTION_EVIDENCE.md</a>.
  </footer>
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark-dashboard.html"))
    args = parser.parse_args()
    dashboard = render_dashboard()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dashboard, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
