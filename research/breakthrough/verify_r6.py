"""Read-only R6 audit: all certificates, full graph orbits, controls and hashes."""

from collections import Counter
import json
import time

from experiment_r1 import HERE, digest
from experiment_r6 import oracle_digest
from lc_certificate_check import brute_lc_css, unpack
from lc_graph_oracle import graph_stabilizers, orbit_table
from lc_projector import solve as old_solve
from lc_r6_corpus import proper_cases
from lc_stitching_check import verify as verify_certificate
from verify_evidence import committed_hash


def verify():
    started = time.perf_counter()
    directory = HERE / "runs/r6"
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    assert all(result[k] == v for k, v in receipt.items())
    for name, value in receipt["hashes"].items():
        assert committed_hash(receipt["source_sha"], name) == value
        assert digest(HERE / name) == value, "use the frozen R6 inputs and verifier components"
    assert digest(directory / "raw.jsonl") == result["raw_sha256"]
    assert digest(directory / "proper_cases.json") == result["cases_sha256"]
    protocol = json.loads((HERE / "protocol_r6.json").read_text())
    cases = json.loads((directory / "proper_cases.json").read_text())
    assert cases == proper_cases(protocol["seed"])
    proper = {case["key"]: case for case in cases}
    tables = {n: orbit_table(n) for n in range(1, 7)}
    assert {str(n): oracle_digest(table) for n, table in tables.items()} == result["oracle_table_hashes"]
    order = [f"graph-{n}-{word}" for n, table in tables.items() for word in sorted(table)] + list(proper)
    counts, families, certificates, per_family = Counter(), Counter(), Counter(), {}
    lifted, ablation, oracle_comparisons, brute_checks = 0, 0, 0, 0
    max_candidates, max_dimension, multi_piece, nontrivial_particular = 0, 0, 0, 0
    index = 0
    with (directory / "raw.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            assert row["key"] == order[index]
            index += 1
            n = row["n"]
            if row["family"] == "graph_state":
                word = row["graph_word"]
                assert row["key"] == f"graph-{n}-{word}"
                assert row["oracle"] == tables[n][word]
                truth = tables[n][word]["css_equivalent"]
                rows = graph_stabilizers(word, n)
            else:
                case = proper[row["key"]]
                assert n == case["n"] and row["family"] == case["family"]
                rows, truth = case["rows"], case["expected"]
                if case["family"] == "random_clifford" and n <= 5:
                    truth = brute_lc_css(unpack(rows, 2 * n))
                    assert truth == row["brute_enumeration"]
                    brute_checks += 1
            candidate = row["candidate"]
            matrix = unpack(rows, 2 * n)
            checked = verify_certificate(matrix, candidate)
            assert checked == row["independent_check"]
            status = candidate["status"]
            assert status != "unresolved"
            assert row["expected"] == truth
            if truth is not None:
                assert (status == "css_equivalent") == truth
                oracle_comparisons += 1
            # Replay the bounded internal comparator; do not reinterpret its timing.
            previous = old_solve(rows, n, seconds=5.)
            assert previous["status"] == row["r5_status"]
            assert previous.get("reason") == row["r5_reason"]
            if previous["status"] == "unresolved":
                lifted += 1
            else:
                assert previous["status"] == status
            if "affine_dimension" in candidate:
                dimension, considered = candidate["affine_dimension"], candidate["candidates_considered"]
                assert considered <= dimension + 1
                max_candidates, max_dimension = max(max_candidates, considered), max(max_dimension, dimension)
                if status == "not_lc_css":
                    ablation += 1
                elif candidate["particular_bad_qubits"]:
                    nontrivial_particular += 1
                if len(candidate.get("cover_pieces", [])) > 1:
                    multi_piece += 1
            counts[status] += 1
            certificates[checked] += 1
            families[row["family"]] += 1
            per_family.setdefault(row["family"], Counter())[status] += 1
    assert index == result["records"] == len(order) == protocol["records_total"] == 34047
    assert counts == result["counts"] and families == result["families"]
    assert certificates == result["certificate_counts"]
    assert lifted == result["previously_unresolved_certified"] == 29
    assert ablation == result["trace_only_ablation_false_positives"] == 144
    assert max_candidates == result["maximum_candidate_maps_considered"] == 146
    assert oracle_comparisons == result["oracle_comparisons"] == 33951
    assert brute_checks == result["proper_code_brute_enumerations"] == 48
    assert result["predictions"] == {"no_disagreement_or_invalid_certificate": True,
                                     "complete_within_budget": True,
                                     "at_least_twelve_r5_unresolved_certified": True,
                                     "trace_only_ablation_refuted": True}
    assert result["elapsed_seconds"] < protocol["resource_limits"]["sweep_seconds"]
    assert result["scientific_breakthrough_gate"] is False and result["mass_indispensability_gate"] is False
    print(json.dumps({"status": "R6_frozen_evidence_verified", "source_sha": receipt["source_sha"],
                      "certificates": dict(certificates), "families": per_family,
                      "exact_oracle_comparisons": oracle_comparisons, "proper_brute_checks": brute_checks,
                      "r5_unresolved_now_certified": lifted, "trace_only_false_positives": ablation,
                      "maximum_affine_dimension": max_dimension, "maximum_maps_considered": max_candidates,
                      "positive_cases_requiring_change_from_particular": nontrivial_particular,
                      "positive_cases_using_multiple_cover_pieces": multi_piece,
                      "elapsed_seconds": time.perf_counter() - started,
                      "independent_researcher_or_novelty_clearance": False}, indent=2))


if __name__ == "__main__":
    verify()
