"""Independent low-pivot, four-variable implementation of the R8 alternative.

No imports from R5/R6 solvers. Full local maps are interleaved a,b,c,d per
site, acting on rows. Negative answers include six linear contradictions.
"""

from itertools import product


PROJECTORS = tuple(p for p in product((0, 1), repeat=4)
                   if p[0] ^ p[3] == 1 and p[0] * p[3] ^ p[1] * p[2] == 0)


def affine(equations, width):
    pivots = {}
    for index, (row, bit) in enumerate(equations):
        if row < 0 or row >= 1 << width or bit not in (0, 1):
            raise ValueError("invalid equation")
        dependency = 1 << index
        while row:
            pivot = (row & -row).bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = (row, bit, dependency)
                break
            old, rhs, dep = pivots[pivot]
            row, bit, dependency = row ^ old, bit ^ rhs, dependency ^ dep
        else:
            if bit:
                return {"consistent": False,
                        "contradiction": [i for i in range(index + 1) if dependency >> i & 1]}

    def backsolve(value, homogeneous):
        for pivot in sorted(pivots, reverse=True):
            row, bit, _ = pivots[pivot]
            if (row & value).bit_count() % 2 ^ (0 if homogeneous else bit):
                value ^= 1 << pivot
        return value

    return {"consistent": True, "particular": backsolve(0, False),
            "basis": [backsolve(1 << j, True) for j in range(width) if j not in pivots],
            "rank": len(pivots)}


def row_basis(rows):
    pivots = {}
    for value in rows:
        while value:
            pivot = (value & -value).bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = value
                break
            value ^= pivots[pivot]
    return [pivots[p] for p in sorted(pivots)]


def dual(rows, width):
    return affine([(r, 0) for r in rows], width)["basis"]


def scalar_components(rows, n):
    mask = (1 << n) - 1
    equations = [(((g & w) ^ ((g >> n) & (w >> n))) & mask, 0)
                 for g in rows for w in dual(rows, 2 * n)]
    basis = affine(equations, n)["basis"]
    groups = {}
    for i in range(n):
        signature = tuple(b >> i & 1 for b in basis)
        groups.setdefault(signature, []).append(i)
    return basis, sorted(groups.values(), key=lambda group: group[0])


def restrict(rows, sites, n):
    size = len(sites)
    return row_basis(sum(((r >> i & 1) << j) | ((r >> (n + i) & 1) << (size + j))
                         for j, i in enumerate(sites)) for r in rows)


def preserving_equations(rows, n):
    equations = []
    for g in rows:
        for w in dual(rows, 2 * n):
            row = 0
            for i in range(n):
                x, z, u, v = g >> i & 1, g >> (n + i) & 1, w >> i & 1, w >> (n + i) & 1
                for k, coefficient in enumerate((x * u, x * v, z * u, z * v)):
                    row |= coefficient << (4 * i + k)
            equations.append((row, 0))
    equations.extend(((1 << (4 * i)) | (1 << (4 * i + 3)), 1) for i in range(n))
    return equations


def gates_for(blocks):
    gates = []
    for a, b, c, d in blocks:
        eigenvectors = []
        for eigenvalue in (1, 0):
            eigenvectors.append(next((x, z) for x, z in ((1, 0), (0, 1), (1, 1))
                                     if (a * x ^ b * z, c * x ^ d * z)
                                     == (eigenvalue * x, eigenvalue * z)))
        first, second = eigenvectors
        gates.append([first[0], second[0], first[1], second[1]])
    return gates


def solve(rows, n):
    if n < 1 or any(not isinstance(r, int) or r < 0 or r >= 1 << (2 * n) for r in rows):
        raise ValueError("invalid binary dimensions")
    rows = row_basis(rows)
    basis, components = scalar_components(rows, n)
    records, blocks, possible = [], [None] * n, True
    for sites in components:
        local = restrict(rows, sites, n)
        equations = preserving_equations(local, len(sites))
        attempts, chosen = [], None
        for anchor in PROJECTORS:
            fixed = equations + [(1 << j, bit) for j, bit in enumerate(anchor)]
            result = affine(fixed, 4 * len(sites))
            if not result["consistent"]:
                attempts.append({"anchor": list(anchor), "consistent": False,
                                 "contradiction": result["contradiction"]})
                continue
            chosen = result["particular"]
            attempts.append({"anchor": list(anchor), "consistent": True,
                             "solution_hex": hex(chosen)})
            for j, i in enumerate(sites):
                blocks[i] = [chosen >> (4 * j + k) & 1 for k in range(4)]
            break
        possible &= chosen is not None
        records.append({"sites": sites, "rows_hex": [hex(r) for r in local],
                        "annihilator_hex": [hex(w) for w in dual(local, 2 * len(sites))],
                        "attempts": attempts})
    return {"status": "css_equivalent" if possible else "not_lc_css", "n": n,
            "scalar_basis_hex": [hex(b) for b in basis], "components": records,
            "anchor_systems": sum(len(c["attempts"]) for c in records),
            "projector_blocks": blocks if possible else None,
            "gates": gates_for(blocks) if possible else None}
