"""Complete finite subspaces and direct finite-span oracle, no solver imports."""

from itertools import combinations, product
import json


def subspaces(width):
    for dimension in range(width + 1):
        for pivots in combinations(range(width), dimension):
            free = [(i, j) for i, pivot in enumerate(pivots)
                    for j in range(pivot + 1, width) if j not in pivots]
            for bits in range(1 << len(free)):
                rows = [1 << pivot for pivot in pivots]
                for k, (i, j) in enumerate(free):
                    rows[i] |= ((bits >> k) & 1) << j
                yield rows


def span(rows):
    values = {0}
    for r in rows:
        values |= {v ^ r for v in values}
    return values


def local_transform(rows, gates, n):
    result = []
    for r in rows:
        value = 0
        for i, (a, b, c, d) in enumerate(gates):
            x, z = r >> i & 1, r >> (n + i) & 1
            value |= (x * a ^ z * c) << i
            value |= (x * b ^ z * d) << (n + i)
        result.append(value)
    return result


def brute_css(rows, n):
    gates = [g for g in product((0, 1), repeat=4) if (g[0] * g[3] + g[1] * g[2]) % 2]
    count, assignments = 0, 0
    mask = (1 << n) - 1
    for frame in product(gates, repeat=n):
        mapped = local_transform(rows, frame, n)
        vectors = span(mapped)
        count += all((r & mask) in vectors and (r & ~mask) in vectors for r in mapped)
        assignments += 1
    return {"positive_frames": count, "assignments": assignments}


def isotropic(rows, n):
    return all(sum(((g >> i & 1) * (h >> (n + i) & 1)
                    + (h >> i & 1) * (g >> (n + i) & 1)) for i in range(n)) % 2 == 0
               for g in rows for h in rows)


def cases(protocol, r7_inputs):
    for n in protocol["all_subspace_qubits"]:
        for index, rows in enumerate(subspaces(2 * n)):
            yield {"key": f"n{n}-s{index}", "family": "all_linear_subspaces", "n": n,
                   "rows_hex": [hex(r) for r in rows]}
    for line in r7_inputs.read_text(encoding="utf-8").splitlines():
        stored = json.loads(line)
        case = stored["case"]
        if case["basis_mode"] == "localized" and case["particular_mode"] == "all_order_three":
            yield {"key": stored["key"], "family": "reused_r7_hard", "n": case["n"],
                   "rows_hex": case["rows_hex"], "expected_components": case["blocks"],
                   "expected_component_size": case["length"]}
