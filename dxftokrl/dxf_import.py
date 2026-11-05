"""DXF-Datei einlesen und in Linien/Bögen (WCS, mm, 2D) zerlegen."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import ezdxf
from ezdxf import recover

from .geometry import Arc, Line, Segment, TAU, arc_from_points, dist

# $INSUNITS -> Faktor nach mm
UNIT_FACTORS = {
    0: (1.0, "ohne Einheit (als mm)"),
    1: (25.4, "Zoll"),
    2: (304.8, "Fuß"),
    4: (1.0, "mm"),
    5: (10.0, "cm"),
    6: (1000.0, "m"),
    8: (0.0000254, "Mikrozoll"),
    9: (0.0254, "Mil"),
    13: (0.001, "µm"),
    14: (100.0, "dm"),
}

MIN_LEN = 1e-6


@dataclass
class ImportResult:
    path: str
    segments: list[tuple[str, Segment]] = field(default_factory=list)
    layer_counts: Counter = field(default_factory=Counter)
    layers_off: set[str] = field(default_factory=set)
    skipped: Counter = field(default_factory=Counter)
    unit_name: str = "mm"
    unit_factor: float = 1.0
    warnings: list[str] = field(default_factory=list)


def _p(v, f: float) -> tuple[float, float]:
    return (float(v[0]) * f, float(v[1]) * f)


class _Importer:
    def __init__(self, result: ImportResult, flatten_tol: float):
        self.r = result
        self.f = result.unit_factor
        # Toleranz für Splines in Zeichnungseinheiten
        self.tol = max(flatten_tol / self.f, 1e-9)

    def add(self, layer: str, seg: Segment) -> None:
        if seg.length() < MIN_LEN:
            return
        self.r.segments.append((layer, seg))
        self.r.layer_counts[layer] += 1

    def add_polyline(self, layer: str, pts) -> None:
        pts = [_p(v, self.f) for v in pts]
        for a, b in zip(pts, pts[1:]):
            if dist(a, b) >= MIN_LEN:
                self.add(layer, Line(a, b))

    def entity(self, e, parent_layer: str | None = None, depth: int = 0) -> None:
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        if parent_layer is not None and layer == "0":
            layer = parent_layer
        f = self.f
        try:
            if t == "LINE":
                self.add(layer, Line(_p(e.dxf.start, f), _p(e.dxf.end, f)))
            elif t == "ARC":
                a0 = e.dxf.start_angle
                span = (e.dxf.end_angle - a0) % 360.0
                if span < 1e-9:
                    span = 360.0
                if span >= 360.0 - 1e-9:
                    self.circle(layer, e)
                    return
                v0, vm, v1 = e.vertices([a0, a0 + span / 2.0, a0 + span])
                self.add(layer, arc_from_points(_p(v0, f), _p(vm, f), _p(v1, f)))
            elif t == "CIRCLE":
                self.circle(layer, e)
            elif t in ("LWPOLYLINE", "POLYLINE"):
                if t == "POLYLINE" and (e.is_polygon_mesh or e.is_poly_face_mesh):
                    self.r.skipped[t + " (Netz)"] += 1
                    return
                for sub in e.virtual_entities():
                    self.entity(sub, layer, depth)
            elif t in ("SPLINE", "ELLIPSE"):
                self.add_polyline(layer, list(e.flattening(self.tol)))
            elif t == "INSERT":
                if depth > 20:
                    self.r.warnings.append("Blockverschachtelung zu tief, abgebrochen.")
                    return
                inserts = e.multi_insert() if e.mcount > 1 else [e]
                for ins in inserts:
                    for sub in ins.virtual_entities():
                        self.entity(sub, layer, depth + 1)
            else:
                self.r.skipped[t] += 1
        except Exception as exc:  # defekte Einzelobjekte überspringen
            self.r.skipped[t + " (fehlerhaft)"] += 1
            if len(self.r.warnings) < 20:
                self.r.warnings.append(f"{t}: {exc}")

    def circle(self, layer: str, e) -> None:
        center = e.ocs().to_wcs(e.dxf.center)
        r = e.dxf.radius * self.f
        if r < MIN_LEN:
            return
        self.add(layer, Arc(_p(center, self.f), r, 0.0, TAU))


def load_dxf(path: str, flatten_tol: float = 0.02) -> ImportResult:
    try:
        doc = ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(path)

    units = int(doc.header.get("$INSUNITS", 0) or 0)
    factor, name = UNIT_FACTORS.get(units, (1.0, f"Einheit {units} (als mm)"))
    result = ImportResult(path=path, unit_name=name, unit_factor=factor)
    for layer in doc.layers:
        if layer.is_off() or layer.is_frozen():
            result.layers_off.add(layer.dxf.name)

    imp = _Importer(result, flatten_tol)
    for e in doc.modelspace():
        imp.entity(e)

    if not result.segments:
        result.warnings.append("Keine verwertbare Geometrie (Linien, Bögen, Kreise, Polylinien, Splines) gefunden.")
    return result

