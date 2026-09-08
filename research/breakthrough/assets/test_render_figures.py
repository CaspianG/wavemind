"""Check rendered scientific marks, standalone SVGs and reproducibility."""

import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest


HERE = Path(__file__).resolve().parent
NS = {"s": "http://www.w3.org/2000/svg"}
SLUGS = ("sensing-model", "pulse-comparison", "drag3-waveform")


def test_render_command_creates_the_requested_outputs(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HERE / "render_figures.py"), "--output-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        f"{slug}.{suffix}" for slug in SLUGS for suffix in ("html", "svg")
    )


def test_check_detects_drift_without_rewriting(tmp_path):
    generate = subprocess.run(
        [sys.executable, str(HERE / "render_figures.py"), "--output-dir", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert generate.returncode == 0, generate.stdout + generate.stderr
    target = tmp_path / "sensing-model.svg"
    target.write_bytes(target.read_bytes() + b"\n")
    changed = target.read_bytes()

    check = subprocess.run(
        [sys.executable, str(HERE / "render_figures.py"), "--output-dir", str(tmp_path), "--check"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert check.returncode != 0
    assert "sensing-model.svg" in check.stdout + check.stderr
    assert target.read_bytes() == changed


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    output = tmp_path_factory.mktemp("research-figures")
    result = subprocess.run(
        [sys.executable, str(HERE / "render_figures.py"), "--output-dir", str(output)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_html_sources_export_to_accessible_standalone_svg(rendered):
    seen_ids = set()
    for slug in SLUGS:
        html = (rendered / f"{slug}.html").read_text(encoding="utf-8")
        svg = (rendered / f"{slug}.svg").read_text(encoding="utf-8")
        root = ET.fromstring(svg)
        assert root.attrib["viewBox"] == "0 0 1280 720"
        assert root.attrib["role"] == "img"
        assert root[0].tag == f"{{{NS['s']}}}title" and root[0].text.strip()
        title, desc = root.find("s:title", NS), root.find("s:desc", NS)
        assert desc.text.strip()
        assert root.attrib["aria-labelledby"].split() == [title.attrib["id"], desc.attrib["id"]]
        ids = [item.attrib["id"] for item in root.iter() if "id" in item.attrib]
        assert len(ids) == len(set(ids)) and not set(ids) & seen_ids
        seen_ids.update(ids)
        assert len(root.findall("s:defs", NS)) == 1
        assert root.find(".//s:text[@data-role='figure-title']", NS) is not None
        assert root.find(".//s:text[@data-role='figure-subtitle']", NS) is not None
        source = root.find(".//s:text[@data-role='source']", NS)
        assert source is not None and source.text.strip().startswith("SOURCE ·")
        assert not re.search(r"<(?:script|foreignObject)\b|\son[a-z]+=", html, re.I)
        assert not re.search(r'(?:fill|stroke)="(?:rgba\(|transparent)', svg)
        assert "fonts.googleapis.com/css2" in html and "@import" in svg


def test_readme_scale_and_safe_editorial_frame(rendered):
    for slug in SLUGS:
        html = (rendered / f"{slug}.html").read_text(encoding="utf-8")
        root = ET.parse(rendered / f"{slug}.svg").getroot()
        assert "<h1" not in html
        title = root.find(".//s:text[@data-role='figure-title']", NS)
        subtitle = root.find(".//s:text[@data-role='figure-subtitle']", NS)
        source = root.find(".//s:text[@data-role='source']", NS)
        assert float(title.attrib["y"]) == 88
        assert float(title.attrib["font-size"]) == 40
        assert float(subtitle.attrib["y"]) == 124
        assert float(subtitle.attrib["font-size"]) >= 18
        assert float(source.attrib["y"]) <= 672
        assert float(source.attrib["font-size"]) >= 16

    model = (rendered / "sensing-model.svg").read_text(encoding="utf-8")
    assert "known phase" in model and "unknown phase" not in model
    bars = ET.parse(rendered / "pulse-comparison.svg").getroot()
    category_labels = bars.findall(".//s:text[@data-role='category-label']", NS)
    value_labels = bars.findall(".//s:text[@data-role='value-label']", NS)
    assert len(category_labels) == len(value_labels) == 8
    assert all(float(label.attrib["font-size"]) >= 20 for label in category_labels)
    assert all(float(label.attrib["font-size"]) >= 18 for label in value_labels)
    tick = next(item for item in bars.findall(".//s:text", NS) if item.text == "0.004")
    axis_title = next(item for item in bars.findall(".//s:text", NS)
                      if item.text == "MINIMUM RATE · NORMALIZED MODEL UNITS")
    assert float(axis_title.attrib["y"]) - float(tick.attrib["y"]) >= 28


def test_small_node_tag_text_is_dark(rendered):
    root = ET.parse(rendered / "sensing-model.svg").getroot()
    control = next(item for item in root.findall(".//s:text", NS)
                   if item.text == "CONTROL")
    assert control.attrib["font-size"] == "12"
    assert control.attrib["fill"] == "#2d3142"


def test_every_arrow_marker_is_used(rendered):
    root = ET.parse(rendered / "sensing-model.svg").getroot()
    marker_ids = {marker.attrib["id"] for marker in root.findall(".//s:marker", NS)}
    referenced_ids = {
        match.group(1)
        for element in root.iter()
        if (marker_end := element.attrib.get("marker-end"))
        and (match := re.fullmatch(r"url\(#([^)]+)\)", marker_end))
    }
    assert marker_ids == referenced_ids


def test_bar_lengths_are_linear_zero_based_and_never_minimum_clamped(rendered):
    data = json.loads((HERE / "figure-data.json").read_text(encoding="utf-8"))
    root = ET.parse(rendered / "pulse-comparison.svg").getroot()
    bars = root.findall(".//s:rect[@data-method]", NS)
    ordered_methods = []
    expected = {}
    for group in data["pulse_comparison"]:
        ordered_methods.extend((group["candidate_id"], group["baseline_id"]))
        expected[group["candidate_id"]] = group["candidate_minimum"]
        expected[group["baseline_id"]] = group["baseline_minimum"]
    assert len(bars) == 8
    assert [bar.attrib["data-method"] for bar in bars] == ordered_methods
    # This independently specified scale is part of the documented figure contract.
    for index, bar in enumerate(bars):
        value = expected[bar.attrib["data-method"]]
        assert float(bar.attrib["x"]) == 352
        assert float(bar.attrib["y"]) == 196 + index * 48
        assert float(bar.attrib["height"]) == 24
        assert float(bar.attrib["data-value"]) == value
        assert float(bar.attrib["width"]) == pytest.approx(value / .016 * 760, abs=1e-9)
    tiny = next(bar for bar in bars if bar.attrib["data-method"] == "FAST_RECT/RS_prefix")
    assert 0 < float(tiny.attrib["width"]) < 1
    accent = [bar for bar in bars if bar.attrib["fill"] == "#eb6c36"]
    assert [bar.attrib["data-method"] for bar in accent] == ["DRAG3/RS_prefix"]


def test_control_traces_preserve_all_samples_on_shared_signed_axis(rendered):
    trace = json.loads((HERE / "figure-data.json").read_text(encoding="utf-8"))["waveform"]
    root = ET.parse(rendered / "drag3-waveform.svg").getroot()
    curves = root.findall(".//s:polyline[@data-component]", NS)
    assert {curve.attrib["data-component"] for curve in curves} == {"X", "Y", "d"}
    assert len(curves) == 3
    assert len({curve.attrib.get("stroke-dasharray", "solid") for curve in curves}) == 3
    for curve in curves:
        points = np.array([[float(number) for number in pair.split(",")]
                           for pair in curve.attrib["points"].split()])
        assert points.shape == (257, 2)
        np.testing.assert_allclose(points[:, 0], 112 + np.array(trace["time"]) / .25 * 1088,
                                   rtol=0, atol=1e-9)
        np.testing.assert_allclose(points[:, 1], 544 - (np.array(trace[curve.attrib["data-component"]]) + 8) / 36 * 360,
                                   rtol=0, atol=1e-9)
        assert np.all((points[:, 1] >= 184) & (points[:, 1] <= 544))


def test_committed_outputs_are_reproducible(rendered):
    for slug in SLUGS:
        for suffix in ("html", "svg"):
            filename = f"{slug}.{suffix}"
            assert (HERE / filename).read_bytes() == (rendered / filename).read_bytes()
