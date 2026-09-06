"""Construct adversarial affine frames on exact elementary stabilizer algebras."""

from itertools import product
import random

import numpy as np


def packed(matrix):
    return sum(int(bit) << i for i, bit in enumerate(matrix.reshape(-1)))


def unpacked(value, n):
    return np.array([(value >> i) & 1 for i in range(4 * n)], dtype=np.uint8).reshape(n, 2, 2)


def generate(length, blocks, seed, basis_mode, particular_mode):
    rng = random.Random(seed)
    n = length * blocks
    cliffords = [g for g in product((0, 1), repeat=4) if (g[0] * g[3] ^ g[1] * g[2]) == 1]
    gates = np.array([rng.choice(cliffords) for _ in range(n)], dtype=np.uint8).reshape(n, 2, 2)
    inverse = gates[:, ::-1, ::-1].copy()
    inverse[:, 0, 1] = gates[:, 0, 1]
    inverse[:, 1, 0] = gates[:, 1, 0]
    order = rng.sample(range(n), n)
    units, rows = [], []
    for block in range(blocks):
        for coordinate in range(2):
            row = np.zeros((n, 2), dtype=np.uint8)
            row[block * length:(block + 1) * length, coordinate] = 1
            row = np.einsum("ni,nij->nj", row, gates) % 2
            row = row[order]
            rows.append(np.concatenate((row[:, 0], row[:, 1])))
        for a in range(2):
            for b in range(2):
                unit = np.zeros((n, 2, 2), dtype=np.uint8)
                unit[block * length:(block + 1) * length, a, b] = 1
                units.append(((inverse @ unit @ gates) % 2)[order])
    rows = np.array(rows, dtype=np.uint8)
    for _ in range(6 * blocks):
        a, b = rng.sample(range(2 * blocks), 2)
        rows[a] ^= rows[b]
    basis, particular = [], np.zeros((n, 2, 2), dtype=np.uint8)
    for block in range(blocks):
        e11, e12, e21, e22 = units[4 * block:4 * block + 4]
        basis.extend([e11 ^ e22, e12.copy(), e21.copy()])
        particular ^= e12 ^ e21 ^ e22
    if basis_mode == "mixed":
        for _ in range(6 * len(basis)):
            a, b = rng.sample(range(len(basis)), 2)
            basis[a] ^= basis[b]
        rng.shuffle(basis)
    elif basis_mode != "localized":
        raise ValueError("unknown basis mode")
    if particular_mode == "shifted":
        for direction in basis:
            if rng.randrange(2):
                particular ^= direction
    elif particular_mode != "all_order_three":
        raise ValueError("unknown particular mode")
    return {"n": n, "length": length, "blocks": blocks, "seed": seed,
            "basis_mode": basis_mode, "particular_mode": particular_mode,
            "rows_hex": [hex(sum(int(bit) << i for i, bit in enumerate(row))) for row in rows],
            "matrix_units_hex": [hex(packed(unit)) for unit in units],
            "particular_hex": hex(packed(particular)), "basis_hex": [hex(packed(v)) for v in basis]}
