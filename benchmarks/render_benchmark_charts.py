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


def pct(value: float) -> str:
    return f"{value:.2f}"


def ms(value: float) -> str:
    return f"{value:.2f} ms"


def svg_text(x: float, y: float, text: str, size: int = 14, weight: str = "400", fill: str = "#172033") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}">{html.escape(text)}</text>'
    )


def svg_rect(x: float, y: float, width: float, height: float, fill: str, radius: int = 4) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(0.0, width):.1f}" '
        f'height="{max(0.0, height):.1f}" rx="{radius}" fill="{fill}" />'
    )


def metric_bar(x: float, y: float, label: str, value: float, color: str, width: float = 300.0) -> list[str]:
    bar_width = max(0.0, min(width, width * value))
    return [
        svg_text(x, y, label, size=13),
        svg_rect(x, y + 8, width, 12, "#e9edf4", radius=6),
        svg_rect(x, y + 8, bar_width, 12, color, radius=6),
        svg_text(x + width + 12, y + 19, pct(value), size=13, weight="700", fill=color),
    ]


def panel(x: float, y: float, width: float, height: float, title: str, subtitle: str) -> list[str]:
    return [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="10" fill="#ffffff" stroke="#d7deea" />',
        svg_text(x + 24, y + 36, title, size=20, weight="700", fill="#111827"),
        svg_text(x + 24, y + 61, subtitle, size=13, fill="#556070"),
    ]


def line_chart(
    x: float,
    y: float,
    width: float,
    height: float,
    points_a: list[tuple[int, float]],
    points_b: list[tuple[int, float]],
) -> list[str]:
    all_values = [value for _, value in points_a + points_b]
    max_value = max(all_values) if all_values else 1.0
    max_value = max(1.0, max_value * 1.15)
    min_memory = min(memory for memory, _ in points_a + points_b)
    max_memory = max(memory for memory, _ in points_a + points_b)
    span = max(1, max_memory - min_memory)

    def xy(memory: int, value: float) -> tuple[float, float]:
        px = x + ((memory - min_memory) / span) * width
        py = y + height - (value / max_value) * height
        return px, py

    lines = [
        f'<line x1="{x:.1f}" y1="{(y + height):.1f}" x2="{(x + width):.1f}" y2="{(y + height):.1f}" stroke="#cbd5e1" />',
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{(y + height):.1f}" stroke="#cbd5e1" />',
    ]
    for tick in (0.0, 0.5, 1.0):
        ty = y + height - tick * height
        value = max_value * tick
        lines.append(f'<line x1="{x:.1f}" y1="{ty:.1f}" x2="{(x + width):.1f}" y2="{ty:.1f}" stroke="#eef2f7" />')
        lines.append(svg_text(x - 44, ty + 4, f"{value:.0f}", size=11, fill="#667085"))

    def series(points: list[tuple[int, float]], color: str) -> list[str]:
        coords = [xy(memory, value) for memory, value in points]
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)
        output = [f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />']
        for (memory, value), (px, py) in zip(points, coords):
            output.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{color}" />')
            output.append(svg_text(px - 20, py - 10, ms(value), size=11, fill=color))
            output.append(svg_text(px - 14, y + height + 20, str(memory), size=11, fill="#667085"))
        return output

    lines.extend(series(points_a, "#246bfe"))
    lines.extend(series(points_b, "#b35c00"))
    lines.append(svg_text(x + width - 170, y - 8, "static agent facts", size=12, fill="#246bfe"))
    lines.append(svg_text(x + width - 170, y + 12, "dynamic memory policy", size=12, fill="#b35c00"))
    lines.append(svg_text(x + width / 2 - 34, y + height + 44, "memories", size=12, fill="#667085"))
    lines.append(svg_text(x - 42, y - 12, "ms", size=12, fill="#667085"))
    return lines


def roadmap_card(x: float, y: float, title: str, status: str, detail: str, color: str) -> list[str]:
    return [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="245" height="70" rx="8" fill="#ffffff" stroke="#d7deea" />',
        svg_rect(x + 16, y + 16, 10, 10, color, radius=5),
        svg_text(x + 34, y + 25, title, size=14, weight="700", fill="#111827"),
        svg_text(x + 16, y + 47, status, size=12, weight="700", fill=color),
        svg_text(x + 16, y + 63, detail, size=11, fill="#667085"),
    ]


def build_svg(root: Path = PROJECT_ROOT) -> str:
    agent = by_engine(load_json(root / "benchmarks" / "agent_memory_results.json"))
    dynamic = by_engine(load_json(root / "benchmarks" / "dynamic_memory_results.json"))
    open_retrieval = by_engine(load_json(root / "benchmarks" / "open_retrieval_scifact_results.json"))
    locomo = by_engine(load_json(root / "benchmarks" / "locomo_evidence_results.json"))
    long_memory = by_engine(load_json(root / "benchmarks" / "long_memory_evidence_results.json"))
    capacity = load_json(root / "benchmarks" / "wavemind_capacity_results.json")

    wm_agent = agent["WaveMind"]
    chroma_agent = agent["Chroma"]
    wm_dynamic = dynamic["WaveMind"]
    chroma_dynamic = dynamic["Chroma static"]
    wm_open = open_retrieval["WaveMind"]
    chroma_open = open_retrieval["Chroma"]
    wm_locomo = locomo["WaveMind"]
    static_locomo = locomo["Static vector"]
    chroma_locomo = locomo["Chroma static"]
    wm_long = long_memory["WaveMind"]
    static_long = long_memory["Static vector"]
    static_points = [
        (int(row["memories"]), float(row["avg_latency_ms"]))
        for row in capacity["static_agent_memory"]
    ]
    dynamic_points = [
        (int(row["memories"]), float(row["avg_latency_ms"]))
        for row in capacity["dynamic_agent_memory"]
    ]

    items: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1180" height="1360" viewBox="0 0 1180 1360" role="img" aria-label="WaveMind benchmark summary">',
        '<rect width="1180" height="1360" fill="#f6f8fb" />',
        svg_text(42, 54, "WaveMind Benchmark Summary", size=30, weight="800", fill="#111827"),
        svg_text(42, 82, "Generated from repository JSON results. Planned public benchmarks are not drawn as wins.", size=14, fill="#556070"),
    ]

    items.extend(panel(40, 120, 520, 245, "Static agent-memory retrieval", "200 facts, 50 natural-language queries, same hash embeddings."))
    items.extend(metric_bar(66, 198, "WaveMind precision@1", float(wm_agent["precision_at_1"]), "#246bfe"))
    items.extend(metric_bar(66, 238, "Chroma precision@1", float(chroma_agent["precision_at_1"]), "#64748b"))
    items.extend(metric_bar(66, 286, "WaveMind precision@3", float(wm_agent["precision_at_3"]), "#246bfe"))
    items.extend(metric_bar(66, 326, "Chroma precision@3", float(chroma_agent["precision_at_3"]), "#64748b"))
    items.append(svg_text(390, 207, f"latency {ms(float(wm_agent['avg_latency_ms']))}", size=12, fill="#246bfe"))
    items.append(svg_text(390, 247, f"latency {ms(float(chroma_agent['avg_latency_ms']))}", size=12, fill="#64748b"))

    items.extend(panel(620, 120, 520, 245, "Dynamic memory policy", "Hotness, TTL, correction, stale suppression, namespace isolation."))
    items.extend(metric_bar(646, 198, "WaveMind precision@1", float(wm_dynamic["precision_at_1"]), "#0a7f5a"))
    items.extend(metric_bar(646, 238, "Chroma static precision@1", float(chroma_dynamic["precision_at_1"]), "#64748b"))
    items.extend(metric_bar(646, 286, "WaveMind stale suppression", float(wm_dynamic["suppression_rate"]), "#0a7f5a"))
    items.extend(metric_bar(646, 326, "Chroma static stale suppression", float(chroma_dynamic["suppression_rate"]), "#64748b"))
    items.append(svg_text(970, 207, f"latency {ms(float(wm_dynamic['avg_latency_ms']))}", size=12, fill="#0a7f5a"))
    items.append(svg_text(970, 247, f"latency {ms(float(chroma_dynamic['avg_latency_ms']))}", size=12, fill="#64748b"))

    items.extend(panel(40, 405, 1100, 205, "Long-term memory evidence", "Synthetic long-history evidence retrieval: profile, preference, correction, TTL, namespace, and filler noise."))
    items.extend(metric_bar(66, 483, "WaveMind evidence recall@5", float(wm_long["evidence_recall_at_k"]), "#7c3aed", width=255))
    items.extend(metric_bar(66, 525, "Static vector precision@1", float(static_long["precision_at_1"]), "#64748b", width=255))
    items.extend(metric_bar(646, 483, "WaveMind stale suppression", float(wm_long["stale_suppression"]), "#7c3aed", width=255))
    items.extend(metric_bar(646, 525, "Static vector stale suppression", float(static_long["stale_suppression"]), "#64748b", width=255))
    items.append(svg_text(390, 492, f"latency {ms(float(wm_long['avg_latency_ms']))}", size=12, fill="#7c3aed"))
    items.append(svg_text(970, 492, f"context saved {float(wm_long['context_budget_saved']):.2f}", size=12, fill="#7c3aed"))
    items.append(svg_text(66, 584, "This is the first proof-shaped benchmark for dynamic agent memory. Public LoCoMo/LongMemEval results are still planned.", size=13, fill="#344054"))

    items.extend(panel(40, 650, 1100, 275, "Capacity and latency curve", "WaveMind-only local runs on NumPy exact index. Quality stays high; dynamic ranking latency is the next target."))
    items.extend(line_chart(105, 735, 970, 115, static_points, dynamic_points))
    items.append(svg_text(66, 895, "Current fact from JSON: static p@1 is 0.94 at 5000 memories; dynamic policy p@1 is 1.00 through 5000 memories.", size=13, fill="#344054"))
    items.append(svg_text(66, 917, "Target: keep public retrieval quality at Chroma/Qdrant parity while cutting dynamic latency below 20 ms at 5000 memories.", size=13, fill="#344054"))
    items.extend(panel(40, 950, 1100, 190, "Public benchmark runs", "Official public datasets with identical hash embeddings. These are retrieval/evidence checks, not final semantic-answer scores."))
    items.extend(metric_bar(66, 1028, "LoCoMo WaveMind evidence recall@5", float(wm_locomo["evidence_recall_at_k"]), "#7c3aed", width=255))
    items.extend(metric_bar(66, 1070, "LoCoMo Chroma static evidence recall@5", float(chroma_locomo["evidence_recall_at_k"]), "#64748b", width=255))
    items.extend(metric_bar(410, 1028, "LoCoMo static vector evidence recall@5", float(static_locomo["evidence_recall_at_k"]), "#94a3b8", width=255))
    items.extend(metric_bar(755, 1028, "BEIR SciFact WaveMind nDCG@10", float(wm_open["ndcg_at_k"]), "#246bfe", width=255))
    items.extend(metric_bar(755, 1070, "BEIR SciFact Chroma nDCG@10", float(chroma_open["ndcg_at_k"]), "#64748b", width=255))
    items.append(svg_text(66, 1122, f"Latency: LoCoMo WaveMind {ms(float(wm_locomo['avg_latency_ms']))} vs Chroma {ms(float(chroma_locomo['avg_latency_ms']))}; SciFact WaveMind {ms(float(wm_open['avg_latency_ms']))} vs Chroma {ms(float(chroma_open['avg_latency_ms']))}.", size=13, fill="#344054"))

    items.extend(panel(40, 1165, 1100, 155, "Public benchmark roadmap", "Completed public runs are evidence. Planned rows below are the next proof path, not claimed wins."))
    items.extend(roadmap_card(66, 1235, "BEIR SciFact", "implemented", "hash retrieval run", "#246bfe"))
    items.extend(roadmap_card(336, 1235, "LoCoMo", "implemented", "evidence retrieval", "#7c3aed"))
    items.extend(roadmap_card(606, 1235, "LongMemEval", "planned", "agent-memory proof", "#b35c00"))
    items.extend(roadmap_card(876, 1235, "VectorDBBench", "planned", "index-scale proof", "#0a7f5a"))
    items.append(svg_text(66, 1342, "Also planned: MTEB Retrieval, MIRACL Russian, ANN-Benchmarks style curve, LMEB, and RAGBench.", size=13, fill="#344054"))
    items.append("</svg>")
    return "\n".join(items) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/assets/benchmark-summary.svg"))
    args = parser.parse_args()
    svg = build_svg()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
