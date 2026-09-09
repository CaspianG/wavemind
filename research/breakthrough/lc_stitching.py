"""R6 polynomial candidate: trace-one algebra, central masks, explicit proofs.

R5 sources remain frozen. This uses its field representation and linear
helpers, but replaces affine enumeration with the argument in LC_STITCHING.md.
"""

import time

from lc_projector import affine_solution, equation, is_css, nullspace, projector_gates, transform, validate_stabilizer


def stitch(particular, basis, n):
    """Returns a packed a,b,c projector, uncovered mask, and cover pieces.

    Caller must supply a complete trace-one slice of a preserving algebra.
    The routine alone is not a solver for arbitrary affine constraints.
    """
    mask = (1 << n) - 1
    remaining, output, pieces = mask, 0, []
    for index in range(len(basis) + 1):
        value = particular if index == 0 else particular ^ basis[index - 1]
        bad = ((value >> n) & mask) & (value >> (2 * n))
        selected = remaining & (mask ^ bad)
        if selected:
            output ^= value & (selected | selected << n | selected << (2 * n))
            pieces.append({"candidate_index": index, "sites_hex": hex(selected)})
            remaining ^= selected
        if not remaining:
            return output, remaining, pieces, index + 1
    return output, remaining, pieces, len(basis) + 1


def solve(rows, n, seconds=12.):
    started = time.perf_counter()
    rank = validate_stabilizer(rows, n)
    dual = nullspace(rows, 2 * n)
    pivots, originals, processed = {}, [], 0
    # Use all supplied rows, including redundant ones, for a transparent map to certificates.
    def finish(status, **fields):
        return {"status": status, "n": n, "stabilizer_rank": rank, "linear_rank": len(pivots),
                "equations_processed": processed, "elapsed_seconds": time.perf_counter() - started,
                "method": "trace_one_central_mask_stitching", **fields}

    def entries(dependency):
        return [{"generator": gi, "annihilator_hex": hex(w)}
                for j, (gi, w) in enumerate(originals) if (dependency >> j) & 1]

    for gi, g in enumerate(rows):
        for w in dual:
            processed += 1
            if processed % 256 == 0 and time.perf_counter() - started > seconds:
                return finish("unresolved", reason="per_code_wall_bound")
            value, rhs = equation(g, w, n)
            dependency = 0
            while value:
                pivot = value.bit_length() - 1
                if pivot not in pivots:
                    dependency ^= 1 << len(originals)
                    originals.append((gi, w))
                    pivots[pivot] = (value, rhs, dependency)
                    break
                old, old_rhs, old_dependency = pivots[pivot]
                value ^= old
                rhs ^= old_rhs
                dependency ^= old_dependency
            else:
                if rhs:
                    return finish("not_lc_css", certificate_type="linear_contradiction",
                                  constraints=entries(dependency) + [{"generator": gi, "annihilator_hex": hex(w)}])
    particular, basis = affine_solution(pivots, 3 * n)
    particular_bad = ((particular >> n) & ((1 << n) - 1)) & (particular >> (2 * n))
    projector, remaining, pieces, tried = stitch(particular, basis, n)
    if remaining:
        qubit = (remaining & -remaining).bit_length() - 1
        forced = []
        for coordinate in (n + qubit, 2 * n + qubit):
            value, rhs, dependency = 1 << coordinate, 0, 0
            while value:
                pivot = value.bit_length() - 1
                if pivot not in pivots:
                    raise AssertionError("uncovered site not forced by linear constraints")
                old, old_rhs, old_dependency = pivots[pivot]
                value ^= old
                rhs ^= old_rhs
                dependency ^= old_dependency
            if rhs != 1:
                raise AssertionError("uncovered site not forced to order-three block")
            forced.append(entries(dependency))
        return finish("not_lc_css", certificate_type="forced_order_three_block", qubit=qubit,
                      forced_b_constraints=forced[0], forced_c_constraints=forced[1],
                      affine_dimension=len(basis), candidates_considered=tried,
                      particular_bad_qubits=particular_bad.bit_count())
    gates = projector_gates(projector, n)
    if not is_css(transform(rows, n, gates), n):
        raise AssertionError("stitched map failed independent-of-construction CSS rank condition")
    return finish("css_equivalent", gates=gates, affine_dimension=len(basis),
                  candidates_considered=tried, cover_pieces=pieces, projector_hex=hex(projector),
                  particular_bad_qubits=particular_bad.bit_count())
