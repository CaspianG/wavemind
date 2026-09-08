"""Protect public research statements and asset provenance without publishing."""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import numpy as np

from build_figure_data import build


HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
REPO = RESEARCH.parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_figure_inputs_replay_without_rendering():
    data = read(HERE / "figure-data.json")
    assert data == build()
    assert len(data["pulse_comparison"]) == 4
    assert all(row["baseline_id"].endswith("/RXY8") for row in data["pulse_comparison"])
    trace = data["waveform"]
    assert all(len(trace[key]) == 257 for key in ("time", "X", "Y", "d"))
    assert trace["time"][0] == 0. and trace["time"][-1] == .25
    assert data["claims"]["advantage_gate_pass"] is False


def test_current_status_matches_v3_and_keeps_mission_gates_closed():
    status = read(RESEARCH / "mission_status.json")
    run = read(RESEARCH / "sensing_rs/runs/pulse_v3/results.json")
    record = status["sensing_pulse_v3_20260908"]
    assert record["candidate"] == run["candidate"]
    assert record["decision"] == run["decision"]
    assert record["engineering_points_per_combination"] == run["points_per_combination"]
    assert record["waveform_sequence_combinations"] == run["combinations"]
    np.testing.assert_allclose(record["candidate_to_best_grid_minimum_ratio"], run["candidate_to_best_minimum_ratio"], rtol=1e-12)
    np.testing.assert_allclose(record["candidate_to_best_grid_median_ratio"], run["candidate_to_best_median_ratio"], rtol=1e-12)
    assert not record["combination_advantage_gate"] and not record["continuous_domain_certified"]
    assert status["scientific_breakthrough_gate"] is False
    assert status["mass_indispensability_gate"] is False
    assert status["published"] is False
    assert status["public_workflow_human_terms_review"] == "pending_actual_human_review"


def test_concept_art_keeps_identity_and_accessible_image_links():
    image = HERE / "quantum-sensing-concept.png"
    assert hashlib.sha256(image.read_bytes()).hexdigest() == "20f97f9b1ab68bf846affa9c5683a547faef37c63950785fd6cd1629db65d6db"
    english = (RESEARCH / "README.md").read_text(encoding="utf-8")
    russian = (RESEARCH / "START_HERE_RU.md").read_text(encoding="utf-8")
    for page in (english, russian):
        images = re.findall(r"!\[([^\]]+)\]\((assets/quantum-sensing-concept.png)\)", page)
        assert len(images) == 1
        assert images[0][0].strip()


def test_research_markdown_local_file_links_resolve():
    paths = [RESEARCH / "README.md", RESEARCH / "START_HERE_RU.md", RESEARCH / "PLAIN_LANGUAGE_RU.md",
             RESEARCH / "sensing_rs/RESULTS_V3_RU.md", RESEARCH / "sensing_rs/VALIDATION_HANDOFF.md",
             HERE / "README.md", HERE / "FIGURE_CONTRACT.md", REPO / "README.md", REPO / "docs/README.md"]
    checked = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", text):
            parts = urlsplit(target)
            if parts.scheme or target.startswith("#"):
                continue
            relative = unquote(parts.path)
            if relative:
                assert (path.parent / relative).is_file(), (path, target)
                checked += 1
    assert checked > 75
