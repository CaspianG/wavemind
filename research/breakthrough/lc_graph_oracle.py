"""Exact small graph-local-complementation orbit oracle, no matrix solver.

CSS graph-state orbit iff some graph in its LC orbit is bipartite. This
oracle uses only edge toggles and graph two-coloring, not projector equations.
"""

from itertools import combinations


def edges(n):
    return list(combinations(range(n), 2))


def neighbors(word, n):
    result = [[] for _ in range(n)]
    for index, (a, b) in enumerate(edges(n)):
        if (word >> index) & 1:
            result[a].append(b)
            result[b].append(a)
    return result


def complement_at(word, n, vertex):
    links = {pair: i for i, pair in enumerate(edges(n))}
    nearby = neighbors(word, n)[vertex]
    for a, b in combinations(nearby, 2):
        word ^= 1 << links[tuple(sorted((a, b)))]
    return word


def bipartite(word, n):
    adjacency = neighbors(word, n)
    colors = {}
    for root in range(n):
        if root in colors:
            continue
        colors[root] = 0
        pending = [root]
        while pending:
            a = pending.pop()
            for b in adjacency[a]:
                if b in colors:
                    if colors[a] == colors[b]:
                        return False
                else:
                    colors[b] = 1 - colors[a]
                    pending.append(b)
    return True


def orbit_table(n):
    result = {}
    for start in range(1 << len(edges(n))):
        if start in result:
            continue
        orbit, pending = {start}, [start]
        while pending:
            word = pending.pop()
            for v in range(n):
                other = complement_at(word, n, v)
                if other not in orbit:
                    orbit.add(other)
                    pending.append(other)
        witnesses = [word for word in orbit if bipartite(word, n)]
        evidence = {"orbit_representative": min(orbit), "orbit_size": len(orbit),
                    "bipartite_witness": min(witnesses) if witnesses else None,
                    "css_equivalent": bool(witnesses)}
        for word in orbit:
            result[word] = evidence
    return result


def graph_stabilizers(word, n):
    return [(1 << i) | sum(1 << (j + n) for j in row)
            for i, row in enumerate(neighbors(word, n))]
