"""Word alignment (Levenshtein with backtrace) and edit distances."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    kind: str  # "ok", "sub", "del", "ins"
    ref: int | None  # index into the reference words
    hyp: int | None  # index into the hypothesis words


def align(ref: list[str], hyp: list[str]) -> list[Op]:
    """Minimum-edit alignment of two word lists, in order."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = ref[i - 1] == hyp[j - 1]
            cost[i][j] = min(cost[i - 1][j - 1] + (0 if same else 1), cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    ops: list[Op] = []
    i, j = n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            ops.append(Op("ok" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(Op("del", i - 1, None))
            i -= 1
        else:
            ops.append(Op("ins", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def distance(a: str, b: str) -> int:
    """Character edit distance."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j - 1] + (ca != cb), previous[j] + 1, current[j - 1] + 1))
        previous = current
    return previous[-1]
