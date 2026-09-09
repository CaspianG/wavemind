"""One exact counterexample to RAW binary-address flags, not to R8 or flag QEC.

Claim under attack: after a hook at data-CNOT boundary j, three unprotected
flags report binary(j); this suffices for one-fault-tolerant extraction of
the weight-eight check of the [[15,7,3]] CSS Hamming code. No flag repetition
or extra distinguishing information is allowed. All ordinary stabilizer
syndromes may be supplied. A lone flag-readout fault is in the fault model.

The collision was derived before execution, not discovered in held-out data.
The circuit must realize the claimed propagation labels; a different label
map or protected readout is a different construction, not a rescue here.
Only integer arithmetic; no dependencies, sampling, network, or file writes.
"""

import json


def audit():
    n = 15
    checks = [sum(1 << (q - 1) for q in range(1, n + 1) if q & (1 << b))
              for b in range(4)]
    stabilizers = {0}
    for check in checks:
        stabilizers |= {word ^ check for word in tuple(stabilizers)}
    assert len(stabilizers) == 16  # rank 4, for both X and Z checks
    assert all((a & b).bit_count() % 2 == 0 for a in checks for b in checks)
    assert {word.bit_count() for word in stabilizers - {0}} == {8}
    columns = [sum(((check >> q) & 1) << b for b, check in enumerate(checks))
               for q in range(n)]
    assert columns == list(range(1, 16))  # no weight-1/2 normalizer word
    assert columns[0] ^ columns[1] ^ columns[2] == 0
    assert 0b111 not in stabilizers  # weight-3 logical X: distance is 3

    measured_sites = list(range(8, 16))
    assert sum(1 << (q - 1) for q in measured_sites) == checks[3]
    boundary = 4
    hook_sites = measured_sites[boundary:]
    hook = sum(1 << (q - 1) for q in hook_sites)
    assert hook_sites == [12, 13, 14, 15]
    hook_syndrome = [(hook & check).bit_count() % 2 for check in checks]
    assert hook_syndrome == [0, 0, 0, 0]
    assert hook not in stabilizers  # undetectable nontrivial logical X

    def coset_weight(word):
        return min((word ^ stabilizer).bit_count() for stabilizer in stabilizers)

    quotient_distance = coset_weight(hook)
    assert quotient_distance == 4
    raw_hook_flags = boundary  # binary address 100
    faulty_readout_flags = 1 << 2  # one flipped flag, no data error
    assert raw_hook_flags == faulty_readout_flags == 4

    common_corrections = 0
    best_worst_residual = n
    for correction in range(1 << n):
        residual = max(coset_weight(correction), coset_weight(correction ^ hook))
        common_corrections += residual <= 1
        best_worst_residual = min(best_worst_residual, residual)
    assert common_corrections == 0 and best_worst_residual == 2

    # Exhausting X components is enough: adding Z/Y cannot lower X support,
    # including after multiplication by any stabilizer of this CSS code.
    return {
        "status": "RAW_SHARED_FLAG_CLAIM_REFUTED",
        "fault_scenarios": 2,
        "faults_per_scenario": 1,
        "flag_record_both": "100",
        "ordinary_stabilizer_syndrome_both": "00000000",
        "data_errors": ["I", "X12 X13 X14 X15"],
        "x_stabilizer_group_size": len(stabilizers),
        "logical_x_coset_distance": quotient_distance,
        "x_corrections_exhausted": 1 << n,
        "common_corrections_with_residual_weight_at_most_one": common_corrections,
        "best_worst_residual_weight": best_worst_residual,
        "refutes_r8": False,
        "refutes_protected_flag_gadgets": False,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
