"""2D-Geometrie: Linien, Kreisbögen und Konturen (alle Maße in mm)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Union

Point = tuple[float, float]
TAU = 2.0 * math.pi


def dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _unit(x: float, y: float) -> Point:
    n = math.hypot(x, y)
    return (x / n, y / n) if n > 0 else (1.0, 0.0)


def arc_segment_count(radius: float, sweep: float, tol: float) -> int:
    """Anzahl Sehnen, damit die Abweichung vom Bogen <= tol bleibt."""
    if radius <= 0:
        return 1
    if tol >= radius:
        return max(1, math.ceil(abs(sweep) / (math.pi / 2)))
    step = 2.0 * math.acos(1.0 - tol / radius)
    return max(1, min(2000, math.ceil(abs(sweep) / step)))


@dataclass(frozen=True)
class Line:
    p0: Point
    p1: Point

    @property
    def start(self) -> Point:
        return self.p0

    @property
    def end(self) -> Point:
        return self.p1

    def length(self) -> float:
        return dist(self.p0, self.p1)

    def reversed(self) -> "Line":
        return Line(self.p1, self.p0)

    def points(self, tol: float) -> list[Point]:
        return [self.p0, self.p1]

    def start_tangent(self) -> Point:
        return _unit(self.p1[0] - self.p0[0], self.p1[1] - self.p0[1])


@dataclass(frozen=True)
class Arc:
    """Kreisbogen. a0 = Startwinkel (rad), sweep = Bogenwinkel (rad, + = gegen Uhrzeigersinn)."""

    center: Point
    radius: float
    a0: float
    sweep: float

    def point_at(self, t: float) -> Point:
        a = self.a0 + self.sweep * t
        return (self.center[0] + self.radius * math.cos(a),
                self.center[1] + self.radius * math.sin(a))

    @property
    def start(self) -> Point:
        return self.point_at(0.0)

    @property
    def end(self) -> Point:
        return self.point_at(1.0)

    @property
    def mid(self) -> Point:
        return self.point_at(0.5)

    @property
    def is_full_circle(self) -> bool:
        return abs(abs(self.sweep) - TAU) < 1e-9

    def length(self) -> float:
        return abs(self.sweep) * self.radius

    def reversed(self) -> "Arc":
        return Arc(self.center, self.radius, self.a0 + self.sweep, -self.sweep)

    def with_start_angle(self, angle: float) -> "Arc":
        """Nur für Vollkreise: gleicher Kreis, anderer Startpunkt."""
        return Arc(self.center, self.radius, angle, self.sweep)

    def split(self, n: int) -> list["Arc"]:
        step = self.sweep / n
        return [Arc(self.center, self.radius, self.a0 + i * step, step) for i in range(n)]

    def sagitta(self) -> float:
        half = min(abs(self.sweep), math.pi) / 2.0
        return self.radius * (1.0 - math.cos(half))

    def points(self, tol: float) -> list[Point]:
        n = arc_segment_count(self.radius, self.sweep, tol)
        return [self.point_at(i / n) for i in range(n + 1)]

    def start_tangent(self) -> Point:
        s = 1.0 if self.sweep >= 0 else -1.0
        return (-math.sin(self.a0) * s, math.cos(self.a0) * s)


Segment = Union[Line, Arc]


def arc_from_points(p0: Point, pm: Point, p1: Point) -> Segment:
    """Bogen durch Start-, Zwischen- und Endpunkt. Fast kollinear -> Linie."""
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    span = max(dist(p0, pm), dist(pm, p1), dist(p0, p1), 1e-9)
    if abs(cross) <= 1e-9 * span * span:
        return Line(p0, p1)
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    if r > 1e6:
        return Line(p0, p1)
    a0 = math.atan2(ay - uy, ax - ux)
    a1 = math.atan2(cy - uy, cx - ux)
    if cross > 0:  # gegen Uhrzeigersinn
        sweep = (a1 - a0) % TAU
    else:
        sweep = -((a0 - a1) % TAU)
    return Arc((ux, uy), r, a0, sweep)


@dataclass
class Contour:
    segments: list[Segment]
    layer: str = "0"
    closed: bool = False
    enabled: bool = True
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def start(self) -> Point:
        return self.segments[0].start

    @property
    def end(self) -> Point:
        return self.segments[-1].end

    def length(self) -> float:
        return sum(s.length() for s in self.segments)

    def reversed(self) -> "Contour":
        return Contour([s.reversed() for s in reversed(self.segments)],
                       self.layer, self.closed, self.enabled)

    def rotated(self, index: int) -> "Contour":
        """Geschlossene Kontur ab Segment `index` beginnen lassen."""
        segs = self.segments[index:] + self.segments[:index]
        return Contour(segs, self.layer, self.closed, self.enabled)

    def points(self, tol: float = 0.05) -> list[Point]:
        key = ("pts", tol)
        if key not in self._cache:
            pts: list[Point] = []
            for s in self.segments:
                sp = s.points(tol)
                pts.extend(sp if not pts else sp[1:])
            self._cache[key] = pts
        return self._cache[key]

    def bbox(self, tol: float = 0.05) -> tuple[float, float, float, float]:
        pts = self.points(tol)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def signed_area(self, tol: float = 0.05) -> float:
        pts = self.points(tol)
        a = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            a += x0 * y1 - x1 * y0
        return a / 2.0

    def start_tangent(self) -> Point:
        return self.segments[0].start_tangent()

    def describe(self) -> str:
        art = "geschlossen" if self.closed else "offen"
        return f"{self.layer} · {art} · {self.length():.1f} mm"
