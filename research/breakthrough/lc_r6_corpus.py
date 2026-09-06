"""Frozen R6 generated control families; separate from the candidate solver."""

import random


def words_to_rows(words):
    n = len(words[0])
    return [sum((int(p in "XY") << i) | (int(p in "ZY") << (i + n))
                for i, p in enumerate(word)) for word in words]


def change_frame(rows, n, rng):
    # Elementary H/S, rather than the solver's local-matrix transformation code.
    for qubit in range(n):
        for _ in range(5):
            if rng.randrange(2):
                rows = [r ^ ((((r >> qubit) ^ (r >> (n + qubit))) & 1)
                             * ((1 << qubit) | (1 << (n + qubit)))) for r in rows]
            else:
                rows = [r ^ (((r >> qubit) & 1) << (n + qubit)) for r in rows]
    order = rng.sample(range(n), n)
    rows = [sum((((r >> old) & 1) << new) | (((r >> (old + n)) & 1) << (new + n))
                for new, old in enumerate(order)) for r in rows]
    if len(rows) > 1:
        for _ in range(3 * len(rows)):
            a, b = rng.sample(range(len(rows)), 2)
            rows[a] ^= rows[b]
    return rows


def random_code(n, rng):
    rows = [1 << (n + i) for i in range(rng.randrange(n + 1))]
    for _ in range(12 * n):
        control, target = rng.sample(range(n), 2)
        rows = [r ^ (((r >> control) & 1) << target)
                ^ (((r >> (n + target)) & 1) << (n + control)) for r in rows]
        q = rng.randrange(n)
        if rng.randrange(2):
            rows = [r ^ ((((r >> q) ^ (r >> (n + q))) & 1)
                         * ((1 << q) | (1 << (n + q)))) for r in rows]
        else:
            rows = [r ^ (((r >> q) & 1) << (n + q)) for r in rows]
    return change_frame(rows, n, rng)


def toric_rows(size):
    count, n = size * size, 2 * size * size
    def h(i, j):
        return (i % size) * size + j % size
    def v(i, j):
        return count + h(i, j)
    x, z = [], []
    for i in range(size):
        for j in range(size):
            x.append(sum(1 << q for q in [h(i, j), h(i - 1, j), v(i, j), v(i, j - 1)]))
            z.append(sum(1 << (q + n) for q in [h(i, j), v(i + 1, j), h(i, j + 1), v(i, j)]))
    return x + z


def proper_cases(seed):
    rng = random.Random(seed)
    cases = []
    def add(family, n, rows, expected=None):
        cases.append({"key": f"{family}-{len(cases):04d}", "family": family, "n": n,
                      "rows": rows, "expected": expected})
    for n in (4, 5, 6, 8, 12, 20):
        for _ in range(24):
            add("random_clifford", n, random_code(n, rng))
    for size in (3, 4, 5):
        n = 2 * size * size
        for _ in range(4):
            add("toric", n, change_frame(toric_rows(size), n, rng), True)
    for pairs in (10, 20, 40, 80):
        n = 2 * pairs
        rows = [3 << (2 * j + shift) for j in range(pairs) for shift in (0, n)]
        for _ in range(3):
            add("bell_products", n, change_frame(rows[:], n, rng), True)
    five = words_to_rows(["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"])
    for extra in (0, 8, 24, 48):
        n = 5 + extra
        rows = [(r & 31) | (r >> 5) << n for r in five]
        for _ in range(3):
            add("five_with_spectators", n, change_frame(rows[:], n, rng), False)
    return cases
