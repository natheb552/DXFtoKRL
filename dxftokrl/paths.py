"""Einzelsegmente zu Konturen verbinden und Bearbeitungsreihenfolge optimieren."""
from __future__ import annotations

import math
from collections import defaultdict, deque

from .geometry import Arc, Contour, Point, Segment, dist


class _EndpointIndex:
    """Rasterindex über Segment-Endpunkte für schnelle Nachbarsuche."""

    def __init__(self, tol: float):
        self.tol = tol
        self.cells: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
        self.points: dict[tuple[int, int], Point] = {}

    def _cell(self, p: Point) -> tuple[int, int]:
        return (math.floor(p[0] / self.tol), math.floor(p[1] / self.tol))

    def add(self, idx: int, which: int, p: Point) -> None:
        self.cells[self._cell(p)].add((idx, which))
        self.points[(idx, which)] = p

    def remove(self, idx: int) -> None:
        for which in (0, 1):
            p = self.points.pop((idx, which), None)
            if p is not None:
                self.cells[self._cell(p)].discard((idx, which))

    def nearest(self, p: Point) -> tuple[int, int] | None:
        cx, cy = self._cell(p)
        best, best_d = None, self.tol
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for key in self.cells.get((cx + dx, cy + dy), ()):
                    d = dist(p, self.points[key])
                    if d <= best_d and (best is None or d < best_d or key < best):
                        best, best_d = key, d
        return best


def _is_full_circle(s: Segment) -> bool:
    return isinstance(s, Arc) and s.is_full_circle


def chain_segments(segments: list[tuple[str, Segment]], tol: float = 0.05) -> list[Contour]:
    """Segmente gleicher Ebene, deren Enden innerhalb `tol` liegen, zu Konturen verketten."""
    tol = max(tol, 1e-6)
    by_layer: dict[str, list[Segment]] = defaultdict(list)
    for layer, seg in segments:
        by_layer[layer].append(seg)

    contours: list[Contour] = []
    for layer, segs in by_layer.items():
        index = _EndpointIndex(tol)
        for i, s in enumerate(segs):
            if not _is_full_circle(s):
                index.add(i, 0, s.start)
                index.add(i, 1, s.end)
        used = [False] * len(segs)

        for i, first in enumerate(segs):
            if used[i]:
                continue
            used[i] = True
            if _is_full_circle(first):
                contours.append(Contour([first], layer, closed=True))
                continue
            index.remove(i)
            chain: deque[Segment] = deque([first])

            def closes() -> bool:
                return len(chain) > 1 and dist(chain[-1].end, chain[0].start) <= tol

            # vorwärts
            while not closes():
                hit = index.nearest(chain[-1].end)
                if hit is None:
                    break
                j, which = hit
                used[j] = True
                index.remove(j)
                chain.append(segs[j] if which == 0 else segs[j].reversed())
            # rückwärts
            while not closes():
                hit = index.nearest(chain[0].start)
                if hit is None:
                    break
                j, which = hit
                used[j] = True
                index.remove(j)
                chain.appendleft(segs[j] if which == 1 else segs[j].reversed())

            contours.append(Contour(list(chain), layer, closed=closes()))
    return contours


def _entry_options(c: Contour, rotate_closed: bool):
    """(Einstiegspunkt, Erzeuger der passenden Konturvariante)."""
    if c.closed and len(c.segments) == 1 and isinstance(c.segments[0], Arc):
        arc = c.segments[0]
        yield None, arc  # Sonderfall Vollkreis: nächster Kreispunkt
        return
    if c.closed:
        if rotate_closed:
            for k, s in enumerate(c.segments):
                yield s.start, k
        else:
            yield c.start, 0
        return
    yield c.start, "fwd"
    yield c.end, "rev"


def optimize_order(contours: list[Contour], start: Point = (0.0, 0.0),
                   rotate_closed: bool = True) -> list[Contour]:
    """Nächster-Nachbar-Reihenfolge; offene Konturen ggf. umdrehen,
    geschlossene ggf. an günstigerem Punkt starten. Deaktivierte Konturen ans Ende."""
    active = [c for c in contours if c.enabled]
    inactive = [c for c in contours if not c.enabled]
    options = [list(_entry_options(c, rotate_closed)) for c in active]
    remaining = set(range(len(active)))
    cur = start
    result: list[Contour] = []
    while remaining:
        best = None  # (dist, idx, option)
        for i in remaining:
            for p, opt in options[i]:
                if p is None:  # Vollkreis
                    arc = opt
                    d = abs(dist(cur, arc.center) - arc.radius)
                else:
                    d = dist(cur, p)
                if best is None or d < best[0] - 1e-12:
                    best = (d, i, p, opt)
        _, i, p, opt = best
        c = active[i]
        if p is None:
            arc = opt
            ang = math.atan2(cur[1] - arc.center[1], cur[0] - arc.center[0]) if cur != arc.center else arc.a0
            c = Contour([arc.with_start_angle(ang)], c.layer, True, c.enabled) if rotate_closed else c
        elif opt == "rev":
            c = c.reversed()
        elif isinstance(opt, int) and opt:
            c = c.rotated(opt)
        result.append(c)
        cur = c.end
        remaining.discard(i)
    return result + inactive
