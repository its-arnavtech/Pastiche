"""Half-open millisecond intervals ``(start, end)`` kept sorted and disjoint."""
from __future__ import annotations

from typing import Iterable

Interval = tuple[int, int]


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def subtract(a: Iterable[Interval], b: Iterable[Interval]) -> list[Interval]:
    """Parts of ``a`` not covered by ``b``."""
    b = merge(b)
    out: list[Interval] = []
    for s, e in merge(a):
        cur = s
        for bs, be in b:
            if be <= cur or bs >= e:
                continue
            if bs > cur:
                out.append((cur, bs))
            cur = max(cur, be)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def intersect(a: Iterable[Interval], b: Iterable[Interval]) -> list[Interval]:
    b = merge(b)
    out: list[Interval] = []
    for s, e in merge(a):
        for bs, be in b:
            lo, hi = max(s, bs), min(e, be)
            if lo < hi:
                out.append((lo, hi))
    return merge(out)


def overlap(intervals: Iterable[Interval], start: int, end: int) -> int:
    return sum(max(0, min(e, end) - max(s, start)) for s, e in intervals)


def total(intervals: Iterable[Interval]) -> int:
    return sum(e - s for s, e in merge(intervals))
