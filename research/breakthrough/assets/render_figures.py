"""Render the frozen quantum-sensing figure evidence as HTML and SVG."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re

from build_figure_data import build


HERE = Path(__file__).resolve().parent
SLUGS = ("sensing-model", "pulse-comparison", "drag3-waveform")
FONT_URL = (
    "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1"
    "&family=Geist:wght@400;500;600"
    "&family=Geist+Mono:wght@400;500;600&display=swap"
)
PAPER = "#f5f5f5"
INK = "#2d3142"
MUTED = "#4f5d75"
ACCENT = "#eb6c36"


def text(value: object) -> str:
    """Escape untrusted content for either SVG text or an attribute."""
    return escape(str(value), quote=True)


def fmt(value: float) -> str:
    """Serialize a data coordinate without moving the supplied value."""
    return repr(float(value))


def defs(slug: str, *, arrows: bool = False) -> str:
    markers = ""
    if arrows:
        markers = f"""
        <marker id="{slug}-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>
        <marker id="{slug}-arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>
        <marker id="{slug}-arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#2e5aa8"/></marker>"""
    return f"      <defs>{markers}\n      </defs>"


def svg_frame(slug: str, title: str, description: str, body: str, *, arrows: bool = False) -> str:
    return f"""    <svg viewBox="0 0 1280 720" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{slug}-title {slug}-desc">
      <title id="{slug}-title">{text(title)}</title>
      <desc id="{slug}-desc">{text(description)}</desc>
{defs(slug, arrows=arrows)}
      <rect width="1280" height="720" fill="{PAPER}"/>
{body}
    </svg>"""


def html_frame(title: str, svg: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{text(title)}</title>
  <link href="{FONT_URL}" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --paper: {PAPER}; --ink: {INK}; --muted: {MUTED}; --accent: {ACCENT}; }}
    body {{ min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 32px; background: var(--paper); color: var(--ink); font-family: 'Geist', system-ui, sans-serif; }}
    .frame {{ width: min(100%, 1280px); }}
    svg {{ display: block; width: 100%; min-width: 900px; height: auto; }}
  </style>
</head>
<body>
  <main class="frame">
{svg}
  </main>
</body>
</html>
"""


def node(x: int, y: int, width: int, height: int, tag: str, name: str, lines: tuple[str, ...],
         *, focal: bool = False, dashed: bool = False) -> str:
    stroke = ACCENT if focal else MUTED
    fill = "rgba(235,108,54,0.08)" if focal else ("rgba(45,49,66,0.02)" if dashed else "#ffffff")
    dash = ' stroke-dasharray="4,4"' if dashed else ""
    center = x + width / 2
    line_markup = "\n".join(
        f'        <text x="{fmt(center)}" y="{y + 88 + index * 20}" fill="{MUTED}" font-size="16" font-family="\'Geist Mono\', monospace" text-anchor="middle">{text(line)}</text>'
        for index, line in enumerate(lines)
    )
    return f"""      <g>
        <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" fill="{PAPER}"/>
        <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{dash}/>
        <rect x="{x + 16}" y="{y + 16}" width="64" height="20" rx="4" fill="none" stroke="{stroke}" stroke-width="0.8"/>
        <text x="{x + 48}" y="{y + 30}" fill="{stroke}" font-size="12" font-family="'Geist Mono', monospace" font-weight="600" text-anchor="middle" letter-spacing="0.12em">{text(tag)}</text>
        <text x="{fmt(center)}" y="{y + 64}" fill="{INK}" font-size="20" font-family="'Geist', sans-serif" font-weight="600" text-anchor="middle">{text(name)}</text>
{line_markup}
      </g>"""


def render_sensing_model(data: dict) -> str:
    metric = data["metric"]
    title = "How the sensing protocol turns control into information"
    body = f"""      <text data-role="figure-title" x="64" y="88" fill="{INK}" font-size="40" font-family="'Instrument Serif', serif">{text(title)}</text>
      <text data-role="figure-subtitle" x="64" y="124" fill="{MUTED}" font-size="18" font-family="'Geist', sans-serif">A finite three-level model — a protocol schematic, not a built device</text>
      <line x1="64" y1="152" x2="1216" y2="152" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>

      <line x1="288" y1="360" x2="368" y2="360" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#sensing-model-arrow)"/>
      <line x1="592" y1="360" x2="672" y2="360" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#sensing-model-arrow)"/>
      <line x1="896" y1="360" x2="976" y2="360" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#sensing-model-arrow)"/>
      <line x1="480" y1="432" x2="480" y2="496" stroke="{MUTED}" stroke-width="1" stroke-dasharray="5,4" marker-end="url(#sensing-model-arrow)"/>
      <rect x="496" y="452" width="120" height="20" rx="4" fill="{PAPER}"/>
      <text x="504" y="466" fill="{MUTED}" font-size="12" font-family="'Geist Mono', monospace" letter-spacing="0.08em">UNWANTED PATH</text>

{node(64, 288, 224, 144, "FIELD", "Weak oscillating field", ("known phase", "weak signal amplitude"))}
{node(368, 288, 224, 144, "CONTROL", "Three-level evolution", ("64 pulses", "shaped drive"), focal=True)}
{node(672, 288, 224, 144, "READOUT", "Finite readout scan", (f"{metric['readout_settings']} settings", "shared protocol"))}
{node(976, 288, 224, 144, "METRIC", "Information / total time", ("worst grid point", f"T = {metric['total_time']}"))}
{node(368, 496, 224, 72, "LEAKAGE", "Third-level excitation", (), dashed=True)}

      <line x1="64" y1="612" x2="1216" y2="612" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>
      <text x="64" y="648" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace">MODEL BOUNDARY</text>
      <text x="248" y="648" fill="{MUTED}" font-size="16" font-family="'Geist', sans-serif">Numerical protocol values; no hardware measurement or continuous-domain certificate.</text>
      <text data-role="source" x="1216" y="668" fill="{MUTED}" font-size="16" font-family="'Geist Mono', monospace" text-anchor="end">SOURCE · protocol_v3.json · frozen experiment {text(data['frozen_experiment_source_commit'][:12])}</text>"""
    svg = svg_frame(
        "sensing-model", title,
        "Protocol model showing a weak field passing through 64-pulse three-level evolution, six finite readouts, and an information-per-total-time metric, with unwanted third-level excitation as a dashed branch.",
        body, arrows=True,
    )
    return html_frame(title, svg)


def render_pulse_comparison(data: dict) -> str:
    title = "Pulse compensation improves both methods"
    rows = []
    for group in data["pulse_comparison"]:
        rows.extend(((group["candidate_id"], group["candidate_minimum"]),
                     (group["baseline_id"], group["baseline_minimum"])))

    grid = []
    for tick in range(5):
        value = tick * 0.004
        x = 352 + tick * 190
        grid.append(f'      <line x1="{x}" y1="176" x2="{x}" y2="572" stroke="rgba(45,49,66,{"0.24" if tick == 0 else "0.08"})" stroke-width="{1 if tick == 0 else 0.8}"/>')
        grid.append(f'      <text x="{x}" y="592" fill="{INK}" font-size="18" font-family="\'Geist Mono\', monospace" text-anchor="middle">{value:.3f}</text>')

    bars = []
    for index, (method, value) in enumerate(rows):
        y = 196 + index * 48
        width = value / 0.016 * 760
        waveform, sequence = method.split("/", 1)
        label = f"{waveform} · {'RS' if sequence == 'RS_prefix' else sequence}"
        fill = ACCENT if method == "DRAG3/RS_prefix" else "#d9dde4"
        stroke = INK if method == "DRAG3/RS_prefix" else MUTED
        bars.append(f"""      <text data-role="category-label" x="328" y="{y + 19}" fill="{INK}" font-size="20" font-family="'Geist', sans-serif" font-weight="600" text-anchor="end">{text(label)}</text>
      <rect data-method="{text(method)}" data-value="{fmt(value)}" x="352" y="{y}" width="{fmt(width)}" height="24" fill="{fill}" stroke="{stroke}" stroke-width="1"/>
      <text data-role="value-label" x="{fmt(352 + width + 12)}" y="{y + 19}" fill="{INK}" font-size="18" font-family="'Geist Mono', monospace">{value:.6g}</text>""")

    body = f"""      <text data-role="figure-title" x="64" y="88" fill="{INK}" font-size="40" font-family="'Instrument Serif', serif">{text(title)}</text>
      <text data-role="figure-subtitle" x="64" y="124" fill="{MUTED}" font-size="18" font-family="'Geist', sans-serif">Finite-grid minima of Fisher information per total time · higher is better · source order retained</text>
      <line x1="64" y1="152" x2="1216" y2="152" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>
{chr(10).join(grid)}
{chr(10).join(bars)}
      <text x="732" y="620" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace" text-anchor="middle" letter-spacing="0.12em">MINIMUM RATE · NORMALIZED MODEL UNITS</text>
      <line x1="64" y1="632" x2="1216" y2="632" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>
      <text x="64" y="648" fill="{INK}" font-size="16" font-family="'Geist', sans-serif">9,216 finite-grid settings per combination; RXY8 averages 32 retained phases on one shared budget.</text>
      <text data-role="source" x="64" y="668" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace">SOURCE · results.json · protocol_v3.json</text>
      <text x="1216" y="668" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace" text-anchor="end">MODEL ONLY · GATE FAILED · CANDIDATE/BEST 98.34% · NO CONTINUOUS GUARANTEE</text>"""
    svg = svg_frame(
        "pulse-comparison", title,
        "Eight finite-grid minima compare RS and best-known RXY8 for four pulse waveforms; DRAG3 with RS is highlighted while the claimed two-times advantage gate remains failed.",
        body,
    )
    return html_frame(title, svg)


def render_drag3_waveform(data: dict) -> str:
    title = "DRAG3 commands three coordinated control components"
    trace = data["waveform"]
    styles = {
        "X": (ACCENT, "", "2.4"),
        "Y": (INK, ' stroke-dasharray="12,8"', "1.6"),
        "d": (MUTED, ' stroke-dasharray="4,8"', "1.6"),
    }
    curves = []
    for component in ("X", "Y", "d"):
        points = " ".join(
            f"{fmt(112 + time / 0.25 * 1088)},{fmt(544 - (amplitude + 8) / 36 * 360)}"
            for time, amplitude in zip(trace["time"], trace[component])
        )
        color, dash, width = styles[component]
        curves.append(
            f'      <polyline data-component="{component}" points="{points}" fill="none" stroke="{color}" stroke-width="{width}"{dash} stroke-linejoin="round" stroke-linecap="round"/>'
        )

    grid = []
    for value in (-8, 0, 8, 16, 24, 28):
        y = 544 - (value + 8) / 36 * 360
        grid.append(f'      <line x1="112" y1="{fmt(y)}" x2="1200" y2="{fmt(y)}" stroke="rgba(45,49,66,{"0.28" if value == 0 else "0.08"})" stroke-width="{1.2 if value == 0 else 0.8}"/>')
        grid.append(f'      <text x="96" y="{fmt(y + 6)}" fill="{INK}" font-size="18" font-family="\'Geist Mono\', monospace" text-anchor="end">{value}</text>')
    for value in (0, .05, .10, .15, .20, .25):
        x = 112 + value / .25 * 1088
        grid.append(f'      <line x1="{fmt(x)}" y1="184" x2="{fmt(x)}" y2="544" stroke="rgba(45,49,66,0.08)" stroke-width="0.8"/>')
        grid.append(f'      <text x="{fmt(x)}" y="576" fill="{INK}" font-size="18" font-family="\'Geist Mono\', monospace" text-anchor="middle">{value:.2f}</text>')

    body = f"""      <text data-role="figure-title" x="64" y="88" fill="{INK}" font-size="40" font-family="'Instrument Serif', serif">{text(title)}</text>
      <text data-role="figure-subtitle" x="64" y="124" fill="{INK}" font-size="18" font-family="'Geist', sans-serif">All 257 supplied samples · signed shared axis · commanded controls, not measured traces</text>
      <line x1="64" y1="152" x2="1216" y2="152" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>
{chr(10).join(grid)}
      <line x1="112" y1="184" x2="112" y2="544" stroke="{INK}" stroke-width="1"/>
      <line x1="112" y1="544" x2="1200" y2="544" stroke="{INK}" stroke-width="1"/>
{chr(10).join(curves)}
      <text x="656" y="596" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace" text-anchor="middle" letter-spacing="0.12em">TIME · τ</text>
      <text x="64" y="364" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace" text-anchor="middle" transform="rotate(-90 64 364)" letter-spacing="0.12em">AMPLITUDE · τ⁻¹</text>
      <line x1="160" y1="616" x2="208" y2="616" stroke="{ACCENT}" stroke-width="2.4"/>
      <text x="220" y="620" fill="{INK}" font-size="18" font-family="'Geist', sans-serif" font-weight="600">X · primary drive</text>
      <line x1="472" y1="616" x2="520" y2="616" stroke="{INK}" stroke-width="1.6" stroke-dasharray="12,8"/>
      <text x="532" y="620" fill="{INK}" font-size="18" font-family="'Geist', sans-serif" font-weight="600">Y · derivative quadrature</text>
      <line x1="864" y1="616" x2="912" y2="616" stroke="{MUTED}" stroke-width="1.6" stroke-dasharray="4,8"/>
      <text x="924" y="620" fill="{INK}" font-size="18" font-family="'Geist', sans-serif" font-weight="600">d · longitudinal control</text>
      <line x1="64" y1="632" x2="1216" y2="632" stroke="rgba(45,49,66,0.12)" stroke-width="0.8"/>
      <text x="64" y="648" fill="{INK}" font-size="16" font-family="'Geist', sans-serif">Equal caps do not imply equal consumed energy; the adjacent research record reports the actual RF cost.</text>
      <text data-role="source" x="1216" y="668" fill="{INK}" font-size="16" font-family="'Geist Mono', monospace" text-anchor="end">SOURCE · pulse_v3.py · figure-data.json · DRAG3 · COMMAND MODEL</text>"""
    svg = svg_frame(
        "drag3-waveform", title,
        "Three commanded DRAG3 control components are plotted from all 257 supplied samples on shared signed time and amplitude axes.",
        body,
    )
    return html_frame(title, svg)


def export_svg(html: str) -> str:
    match = re.search(r"<svg\b[\s\S]*?</svg>", html)
    if match is None:
        raise ValueError("Rendered HTML contains no SVG")
    svg = match.group(0)
    opening = svg[:svg.index(">") + 1]
    if not re.search(r"\bviewBox=", opening):
        raise ValueError("Rendered SVG has no viewBox")
    if not re.search(r"\bxmlns=", opening):
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    if "<defs" not in svg:
        raise ValueError("Rendered SVG has no defs block")
    font_import = f"<style>@import url('{FONT_URL.replace('&', '&amp;')}');</style>"
    svg = re.sub(r"(<defs(?:\s[^>]*)?>)", rf"\1\n        {font_import}", svg, count=1)
    svg = re.sub(
        r'(fill|stroke)="rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d*\.?\d+)\s*\)"',
        lambda match: '{}="#{:02x}{:02x}{:02x}" {}-opacity="{}"'.format(
            match.group(1), int(match.group(2)), int(match.group(3)), int(match.group(4)),
            match.group(1), match.group(5),
        ),
        svg,
    )
    svg = re.sub(r'(fill|stroke)="transparent"', r'\1="none"', svg)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n"


def render_all(data: dict) -> dict[str, str]:
    html_outputs = {
        "sensing-model": render_sensing_model(data),
        "pulse-comparison": render_pulse_comparison(data),
        "drag3-waveform": render_drag3_waveform(data),
    }
    outputs: dict[str, str] = {}
    for slug in SLUGS:
        outputs[f"{slug}.html"] = html_outputs[slug]
        outputs[f"{slug}.svg"] = export_svg(html_outputs[slug])
    return outputs


def verified_data() -> dict:
    frozen = json.loads((HERE / "figure-data.json").read_text(encoding="utf-8"))
    if frozen != build():
        raise ValueError("Figure inputs differ from verified frozen evidence")
    return frozen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    parser.add_argument("--check", action="store_true", help="verify identical output bytes without writing")
    args = parser.parse_args()

    outputs = render_all(verified_data())
    if args.check:
        mismatches = [name for name, content in outputs.items()
                      if not (args.output_dir / name).is_file()
                      or (args.output_dir / name).read_bytes() != content.encode("utf-8")]
        if mismatches:
            print("FIGURE_OUTPUT_DRIFT: " + ", ".join(mismatches))
            return 1
        print("FIGURE_OUTPUTS_MATCH: 3 HTML + 3 standalone SVG")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (args.output_dir / name).write_text(content, encoding="utf-8", newline="\n")
    print("RENDERED: " + ", ".join(outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
