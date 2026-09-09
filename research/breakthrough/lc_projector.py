"""Exact local-Clifford-to-CSS certificates; no floating point or QEC package.

Rows pack X in low n bits and Z in high n bits. Projector variables pack
a, b, c in consecutive n-bit blocks, for row action [[a,b],[c,1+a]].
See LC_PROJECTOR.md for the proof and exponential worst-case boundary.
"""

from itertools import product
import time


CLIFFORDS = tuple((a, b, c, d) for a, b, c, d in product(range(2), repeat=4)
                 if (a * d ^ b * c) == 1)


def echelon(rows):
    pivots = {}
    for value in rows:
        while value:
            pivot = value.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = value
                break
            value ^= pivots[pivot]
    return pivots


def nullspace(rows, width):
    pivots = echelon(rows)
    result = []
    for free in range(width):
        if free in pivots:
            continue
        value = 1 << free
        for pivot in sorted(pivots):
            if (pivots[pivot] & value).bit_count() & 1:
                value |= 1 << pivot
        result.append(value)
    return result


def pbb_rows(record):
    """Regular representation of Z_ell x Z_m, row -> row + monomial."""
    ell, m = record["ell"], record["m"]
    size, n = ell * m, 2 * ell * m

    def poly(terms, inverse=False):
        result = []
        direction = -1 if inverse else 1
        for i in range(ell):
            for j in range(m):
                row = 0
                for dx, dy in terms:
                    col = ((i + direction * dx) % ell) * m + (j + direction * dy) % m
                    row ^= 1 << col
                result.append(row)
        return result

    a, b, c, d = [poly(record[key + "_terms"]) for key in "ABCD"]
    at, bt = [poly(record[key + "_terms"], inverse=True) for key in "AB"]
    return ([a[i] | b[i] << size | (c[i] | d[i] << size) << n for i in range(size)]
            + [(bt[i] | at[i] << size) << n for i in range(size)])


def validate_stabilizer(rows, n):
    if n < 1 or any(r < 0 or r >= 1 << (2 * n) for r in rows):
        raise ValueError("invalid binary stabilizer dimensions")
    mask = (1 << n) - 1
    for i, a in enumerate(rows):
        ax, az = a & mask, a >> n
        for b in rows[:i]:
            if ((ax & (b >> n)) ^ (az & b)).bit_count() & 1:
                raise ValueError("noncommuting input stabilizers")
    return len(echelon(rows))


def transform(rows, n, gates):
    if len(gates) != n or any(tuple(g) not in CLIFFORDS for g in gates):
        raise ValueError("not a product of invertible local binary maps")
    masks = [sum(g[k] << i for i, g in enumerate(gates)) for k in range(4)]
    low = (1 << n) - 1
    return [((r & masks[0]) ^ ((r >> n) & masks[2]))
            | ((((r & low) & masks[1]) ^ ((r >> n) & masks[3])) << n)
            for r in rows]


def is_css(rows, n):
    mask = (1 << n) - 1
    return (len(echelon(rows)) == len(echelon(r & mask for r in rows))
            + len(echelon(r >> n for r in rows)))


def uniform_block_baseline(rows, n):
    """Independent implementation of the published 36-pattern rank baseline.

    NOT an execution of the upstream package or its other restricted tests.
    """
    for first, second in product(CLIFFORDS, repeat=2):
        gates = [first] * (n // 2) + [second] * (n - n // 2)
        if is_css(transform(rows, n, gates), n):
            return {"status": "css_equivalent", "gates": gates}
    return {"status": "no_uniform_two_block_witness"}


def equation(g, w, n):
    mask = (1 << n) - 1
    x, z, u, v = g & mask, g >> n, w & mask, w >> n
    return ((x & u) ^ (z & v)) | ((x & v) << n) | ((z & u) << (2 * n)), (z & v).bit_count() & 1


def affine_solution(pivots, width):
    def backsolve(value, homogeneous):
        for pivot in sorted(pivots):
            row, rhs = pivots[pivot][:2]
            if ((row & value).bit_count() & 1) ^ (0 if homogeneous else rhs):
                value |= 1 << pivot
        return value
    particular = backsolve(0, False)
    basis = [backsolve(1 << free, True) for free in range(width) if free not in pivots]
    return particular, basis


def affine_members(particular, basis):
    value, previous_gray = particular, 0
    yield value
    for index in range(1, 1 << len(basis)):
        gray = index ^ (index >> 1)
        value ^= basis[(gray ^ previous_gray).bit_length() - 1]
        previous_gray = gray
        yield value


def projector_gates(value, n):
    result = []
    for i in range(n):
        a, b, c = [(value >> (i + j * n)) & 1 for j in range(3)]
        if b & c:
            raise ValueError("not an idempotent")
        # Columns of C are right eigenvectors of P: P C = C diag(1,0).
        eigen = []
        for lam in (1, 0):
            eigen.append(next((x, z) for x, z in ((0, 1), (1, 0), (1, 1))
                              if ((a * x ^ b * z) == lam * x
                                  and (c * x ^ (1 ^ a) * z) == lam * z)))
        result.append((eigen[0][0], eigen[1][0], eigen[0][1], eigen[1][1]))
    return result


def solve(rows, n, max_dimension=18, seconds=12.):
    started = time.perf_counter()
    deadline = started + seconds
    rank = validate_stabilizer(rows, n)
    # Only independent input generators are needed; retain their original indices.
    independent, selected = {}, []
    for index, row in enumerate(rows):
        reduced = row
        while reduced:
            pivot = reduced.bit_length() - 1
            if pivot not in independent:
                independent[pivot] = reduced
                selected.append(index)
                break
            reduced ^= independent[pivot]
    dual = nullspace(rows, 2 * n)  # ordinary dot-product annihilator, not symplectic
    pivots, originals, processed = {}, [], 0

    def finish(status, **fields):
        return {"status": status, "n": n, "stabilizer_rank": rank,
                "linear_rank": len(pivots), "equations_processed": processed,
                "elapsed_seconds": time.perf_counter() - started, **fields}

    def proof_entries(entries):
        return [{"generator": gi, "annihilator_hex": hex(w)} for gi, w in entries]

    for gi in selected:
        for w in dual:
            processed += 1
            if processed % 256 == 0 and time.perf_counter() > deadline:
                return finish("unresolved", reason="per_code_wall_bound")
            row, rhs = equation(rows[gi], w, n)
            dependency = 0
            while row:
                pivot = row.bit_length() - 1
                if pivot not in pivots:
                    dependency ^= 1 << len(originals)
                    originals.append((gi, w))
                    pivots[pivot] = (row, rhs, dependency)
                    break
                old, old_rhs, old_dependency = pivots[pivot]
                row, rhs, dependency = row ^ old, rhs ^ old_rhs, dependency ^ old_dependency
            else:
                if rhs:
                    chosen = [item for i, item in enumerate(originals) if (dependency >> i) & 1]
                    return finish("not_lc_css", certificate_type="linear_contradiction",
                                  constraints=proof_entries(chosen + [(gi, w)]))
    particular, basis = affine_solution(pivots, 3 * n)
    dimension = len(basis)
    if dimension > max_dimension:
        return finish("unresolved", reason="affine_dimension_bound", affine_dimension=dimension)
    mask = (1 << n) - 1
    for count, value in enumerate(affine_members(particular, basis), start=1):
        if count % 256 == 0 and time.perf_counter() > deadline:
            return finish("unresolved", reason="per_code_wall_bound", affine_dimension=dimension)
        if not (((value >> n) & mask) & (value >> (2 * n))):
            gates = projector_gates(value, n)
            if not is_css(transform(rows, n, gates), n):
                raise AssertionError("candidate witness failed direct CSS rank check")
            return finish("css_equivalent", gates=gates, affine_dimension=dimension,
                          assignments_checked=count, projector_hex=hex(value))
    return finish("not_lc_css", certificate_type="affine_exhaustion",
                  affine_dimension=dimension, assignments_checked=1 << dimension,
                  constraints=proof_entries(originals))
