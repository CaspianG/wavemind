from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _engine(results: dict, name: str) -> dict:
    for row in results.get("results", []):
        if row.get("engine") == name:
            return row
    return {}


def _bar(x: int, y: int, width: int, value: float, color: str) -> str:
    value = max(0.0, min(1.0, float(value)))
    filled = int(width * value)
    return f'<rect x="{x}" y="{y}" width="{width}" height="18" rx="4" fill="#e8edf5"/><rect x="{x}" y="{y}" width="{filled}" height="18" rx="4" fill="{color}"/>'


def _text(x: int, y: int, body: str, size: int = 14, weight: int = 400, color: str = "#111827") -> str:
    escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<text x="{x}" y="{y}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}">{escaped}</text>'


def render_svg(root: Path = PROJECT_ROOT) -> str:
    agent = _load_json(root / "benchmarks" / "agent_memory_results.json")
    dynamic = _load_json(root / "benchmarks" / "dynamic_memory_results.json")
    capacity = _load_json(root / "benchmarks" / "wavemind_capacity_results.json")

    wave = _engine(agent, "WaveMind")
    chroma = _engine(agent, "Chroma")
    dyn_wave = _engine(dynamic, "WaveMind")
    dyn_chroma = _engine(dynamic, "Chroma static")
    static_curve = capacity["static_agent_memory"]
    dynamic_curve = capacity["dynamic_agent_memory"]

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="760" viewBox="0 0 1180 760" role="img" aria-label="WaveMind benchmark summary">',
        '<rect width="1180" height="760" fill="#f6f8fb" />',
        _text(42, 54, "WaveMind Benchmark Summary", 30, 800),
        _text(42, 82, "Generated from repository JSON results. Planned public benchmarks are not drawn as wins.", 14, 400, "#556070"),
    ]

    # Static retrieval panel.
    parts += [
        '<rect x="40" y="120" width="520" height="245" rx="10" fill="#ffffff" stroke="#d7deea" />',
        _text(64, 154, "Static agent-memory retrieval", 20, 750),
        _text(64, 184, "200 facts / 50 queries, same hash embeddings", 13, 400, "#667085"),
        _text(64, 222, f"WaveMind p@1 {wave.get('precision_at_1', 0):.2f}, p@3 {wave.get('precision_at_3', 0):.2f}, {wave.get('avg_latency_ms', 0):.2f} ms", 14),
        _bar(64, 238, 360, wave.get("precision_at_3", 0), "#2563eb"),
        _text(64, 286, f"Chroma p@1 {chroma.get('precision_at_1', 0):.2f}, p@3 {chroma.get('precision_at_3', 0):.2f}, {chroma.get('avg_latency_ms', 0):.2f} ms", 14),
        _bar(64, 302, 360, chroma.get("precision_at_3", 0), "#16a34a"),
    ]

    # Dynamic policy panel.
    parts += [
        '<rect x="620" y="120" width="520" height="245" rx="10" fill="#ffffff" stroke="#d7deea" />',
        _text(644, 154, "Dynamic memory policy", 20, 750),
        _text(644, 184, "Hotness, TTL, corrections, namespace isolation", 13, 400, "#667085"),
        _text(644, 222, f"WaveMind stale suppression {dyn_wave.get('suppression_rate', 0):.2f}, {dyn_wave.get('avg_latency_ms', 0):.2f} ms", 14),
        _bar(644, 238, 360, dyn_wave.get("suppression_rate", 0), "#7c3aed"),
        _text(644, 286, f"Chroma static stale suppression {dyn_chroma.get('suppression_rate', 0):.2f}, {dyn_chroma.get('avg_latency_ms', 0):.2f} ms", 14),
        _bar(644, 302, 360, dyn_chroma.get("suppression_rate", 0), "#f59e0b"),
    ]

    # Capacity panel.
    parts += [
        '<rect x="40" y="410" width="1100" height="285" rx="10" fill="#ffffff" stroke="#d7deea" />',
        _text(64, 444, "Capacity and latency curve", 20, 750),
        _text(64, 472, "Static recall stays high at 5000, dynamic memory latency is the next optimization target.", 13, 400, "#667085"),
    ]
    xs = {200: 180, 1000: 500, 5000: 820}
    base_y = 628
    for row in static_curve:
        x = xs[row["memories"]]
        y = base_y - int(row["precision_at_1"] * 115)
        parts.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#2563eb" />')
        parts.append(_text(x - 28, base_y + 28, str(row["memories"]), 12, 600, "#475467"))
    for row in dynamic_curve:
        x = xs[row["memories"]] + 32
        y = base_y - int(min(row["avg_latency_ms"], 60) / 60 * 115)
        parts.append(f'<rect x="{x - 7}" y="{y - 7}" width="14" height="14" rx="3" fill="#7c3aed" />')
    parts += [
        _text(920, 520, "blue dots: static precision@1", 13, 600, "#2563eb"),
        _text(920, 546, "purple squares: dynamic latency", 13, 600, "#7c3aed"),
        _text(64, 724, "This chart is evidence, not decoration: it separates completed local runs from planned public benchmarks.", 13, 400, "#556070"),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "docs" / "assets" / "benchmark-summary.svg")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_svg(), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
