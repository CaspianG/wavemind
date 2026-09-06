"""Exact finite-horizon Bayes diagnosis for small, declared stationary models."""

from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from itertools import product


@dataclass(frozen=True)
class Problem:
    # likelihood_one[test][world]; tests conditionally independent given world.
    likelihood_one: tuple[tuple[F, ...], ...]
    costs: tuple[F, ...]
    losses: tuple[tuple[F, ...], ...]

    def __post_init__(self):
        if not self.losses or not self.losses[0]:
            raise ValueError("at least one world and stopping action required")
        n = len(self.losses[0])
        if len(self.costs) != len(self.likelihood_one):
            raise ValueError("one cost per test required")
        if any(len(row) != n for row in self.losses + self.likelihood_one):
            raise ValueError("inconsistent world dimension")
        if any(not F(0) <= p <= F(1) for row in self.likelihood_one for p in row):
            raise ValueError("invalid likelihood")
        if any(x < 0 for x in self.costs) or any(x < 0 for row in self.losses for x in row):
            raise ValueError("negative costs or losses")


def dot(a, b):
    return sum((x * y for x, y in zip(a, b, strict=True)), F(0))


def branch(belief, likelihood, outcome):
    weighted = tuple(p * (q if outcome else 1 - q) for p, q in zip(belief, likelihood, strict=True))
    probability = sum(weighted, F(0))
    return probability, tuple(x / probability for x in weighted) if probability else None


def solve(problem, initial_belief, horizon):
    belief = tuple(F(x) for x in initial_belief)
    if horizon < 0 or sum(belief) != 1 or any(x < 0 for x in belief):
        raise ValueError("invalid horizon or prior")
    if len(belief) != len(problem.losses[0]):
        raise ValueError("prior dimension mismatch")

    @lru_cache(maxsize=None)
    def value(b, remaining):
        risks = [dot(b, row) for row in problem.losses]
        action = min(range(len(risks)), key=risks.__getitem__)
        best = (risks[action], F(0), ("stop", action))
        if remaining:
            for test, likelihood in enumerate(problem.likelihood_one):
                risk, probes = problem.costs[test], F(1)
                for outcome in [0, 1]:
                    probability, updated = branch(b, likelihood, outcome)
                    if updated is not None:
                        future_risk, future_probes, _ = value(updated, remaining - 1)
                        risk += probability * future_risk
                        probes += probability * future_probes
                # Prefer stopping/fewer probes on exact risk ties, then stable order.
                if (risk, probes) < best[:2]:
                    best = (risk, probes, ("test", test))
        return best

    risk, probes, action = value(belief, horizon)
    return {"risk": risk, "expected_probes": probes, "root_action": action,
            "cached_states": value.cache_info().currsize}


def enumerate_policy_vectors(problem, horizon):
    """Independent brute-force policy tree enumeration, useful only at tiny depth.

    Computes a vector of total expected loss conditioned on each true world.
    It never computes posteriors or calls the dynamic program.
    """
    vectors = list(problem.losses)
    if horizon:
        children = enumerate_policy_vectors(problem, horizon - 1)
        for test, likelihood in enumerate(problem.likelihood_one):
            for negative, positive in product(children, repeat=2):
                vectors.append(tuple(problem.costs[test] + (1 - p) * a + p * b
                                     for p, a, b in zip(likelihood, negative, positive, strict=True)))
    return vectors


def sign_problem(noise, cost):
    # R3 at pi/2: X is uninformative; Y reports Hamiltonian sign with readout noise.
    return Problem(likelihood_one=((F(1, 2), F(1, 2)), (F(noise), 1 - F(noise))),
                   costs=(F(cost), F(cost)), losses=((F(0), F(1)), (F(1), F(0))))
