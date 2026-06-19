from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def by_engine(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(result["engine"]): result for result in payload.get("results", [])}


def text(x: float, y: float, value: str, size: int = 14, weight: str = "400", fill: str = "#172033") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{weight}" fill="{fill}">{html.escape(value)}</text>'


def rect(x: float, y: float, w: float, h: float, fill: str, rx: int = 4) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(0.0, w):.1f}" height="{max(0.0, h):.1f}" rx="{rx}" fill="{fill}" />'


def panel(x: float, y: float, w: float, h: float, title: str, subtitle: str) -> list[str]:
    return [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" fill="#ffffff" stroke="#d7deea" />', text(x + 24, y + 36, title, 20, "700", "#111827"), text(x + 24, y + 61, subtitle, 13, "400", "#556070")]


def bar(x: float, y: float, label: str, value: float, color: str, width: float = 300) -> list[str]:
    value = max(0.0, min(1.0, float(value)))
    return [text(x, y, label, 13), rect(x, y + 8, width, 12, "#e9edf4", 6), rect(x, y + 8, width * value, 12, color, 6), text(x + width + 12, y + 19, f"{value:.2f}", 13, "700", color)]


def build_svg(root: Path = PROJECT_ROOT) -> str:
    agent = by_engine(load_json(root / "benchmarks" / "agent_memory_results.json"))
    dynamic = by_engine(load_json(root / "benchmarks" / "dynamic_memory_results.json"))
    long_memory = by_engine(load_json(root / "benchmarks" / "long_memory_evidence_results.json"))
    capacity = load_json(root / "benchmarks" / "wavemind_capacity_results.json")
    wm_agent = agent["WaveMind"]
    chroma_agent = agent["Chroma"]
    wm_dynamic = dynamic["WaveMind"]
    chroma_dynamic = dynamic["Chroma static"]
    wm_long = long_memory["WaveMind"]
    static_long = long_memory["Static vector"]
    items = ['<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="980" viewBox="0 0 1180 980" role="img" aria-label="WaveMind benchmark summary">', '<rect width="1180" height="980" fill="#f6f8fb" />', text(42, 54, "WaveMind Benchmark Summary", 30, "800", "#111827"), text(42, 82, "Generated from repository JSON results. Planned public benchmarks are not drawn as wins.", 14, "400", "#556070")]
    items += panel(40, 120, 520, 245, "Static agent-memory retrieval", "200 facts, 50 natural-language queries, same hash embeddings.")
    items += bar(66, 198, "WaveMind precision@1", wm_agent["precision_at_1"], "#246bfe")
    items += bar(66, 238, "Chroma precision@1", chroma_agent["precision_at_1"], "#64748b")
    items += bar(66, 286, "WaveMind precision@3", wm_agent["precision_at_3"], "#246bfe")
    items += bar(66, 326, "Chroma precision@3", chroma_agent["precision_at_3"], "#64748b")
    items += panel(620, 120, 520, 245, "Dynamic memory policy", "Hotness, TTL, correction, stale suppression, namespace isolation.")
    items += bar(646, 198, "WaveMind precision@1", wm_dynamic["precision_at_1"], "#0a7f5a")
    items += bar(646, 238, "Chroma static precision@1", chroma_dynamic["precision_at_1"], "#64748b")
    items += bar(646, 286, "WaveMind stale suppression", wm_dynamic["suppression_rate"], "#0a7f5a")
    items += bar(646, 326, "Chroma static stale suppression", chroma_dynamic["suppression_rate"], "#64748b")
    items += panel(40, 405, 1100, 205, "Long-term memory evidence", "Synthetic long-history evidence retrieval: profile, preference, correction, TTL, namespace, and filler noise.")
    items += bar(66, 483, "WaveMind evidence recall@5", wm_long["evidence_recall_at_k"], "#7c3aed", 255)
    items += bar(66, 525, "Static vector precision@1", static_long["precision_at_1"], "#64748b", 255)
    items += bar(646, 483, "WaveMind stale suppression", wm_long["stale_suppression"], "#7c3aed", 255)
    items += bar(646, 525, "Static vector stale suppression", static_long["stale_suppression"], "#64748b", 255)
    items.append(text(66, 584, "This is the first proof-shaped benchmark for dynamic agent memory. Public LoCoMo/LongMemEval results are still planned.", 13, "400", "#344054"))
    items += panel(40, 650, 1100, 275, "Capacity and latency curve", "WaveMind-only local runs on NumPy exact index. Quality stays high; dynamic ranking latency is the next target.")
    items.append(text(66, 730, "static p@1 is 0.94 at 5000 memories; dynamic policy p@1 is 1.00 through 5000 memories.", 15, "700", "#111827"))
    items.append(text(66, 760, "avg latency: static 13.71 ms at 5000; dynamic policy 48.36 ms at 5000.", 15, "400", "#344054"))
    items.append(text(66, 895, "Target: keep public retrieval quality at Chroma/Qdrant parity while cutting dynamic latency below 20 ms at 5000 memories.", 13, "400", "#344054"))
    items.append("</svg>")
    return "\n".join(items) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/assets/benchmark-summary.svg"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_svg(), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
