"""KRL-Erzeugung für KUKA KR C2 (KSS 5.x): .src + .dat."""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from .geometry import Arc, Contour, Line, Point, dist
from .settings import Settings

VEL_CP_MAX = 2.0          # m/s, übliche Obergrenze KR C2
MAX_CIRC_SWEEP = math.radians(179.0)
MIN_CIRC_CHORD = 0.01     # mm, kleinere Bögen -> LIN
MIN_CIRC_SAGITTA = 0.001  # mm, flachere Bögen -> LIN
MAX_NAME = 24

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
                          "ß": "ss", "µ": "u", "°": "Grad", "·": "-"})


def ascii_text(text: str) -> str:
    """Kommentartext für die Steuerung: nur druckbares ASCII."""
    text = str(text).translate(_UMLAUTE)
    return "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in text)


def sanitize_name(name: str) -> str:
    """Gültiger KRL-/Dateiname: Buchstabe am Anfang, A-Z 0-9 _, max. 24 Zeichen."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", ascii_text(name).strip())
    if not s or not s[0].isalpha():
        s = "P" + s
    return s[:MAX_NAME]


def fmt(v: float, decimals: int = 3) -> str:
    s = f"{v:.{decimals}f}"
    if float(s) == 0.0:
        s = f"{0.0:.{decimals}f}"
    return s


def fmt_short(v: float) -> str:
    """Zahl ohne überflüssige Nullen (für Zeiten, Geschwindigkeiten)."""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def origin_shift(contours: list[Contour], s: Settings) -> tuple[float, float]:
    """Verschiebung DXF -> BASE (wird auf alle Punkte addiert)."""
    g = s.general
    dx, dy = g.offset_x, g.offset_y
    if g.origin_mode == "bbox_min":
        active = [c for c in contours if c.enabled]
        if active:
            boxes = [c.bbox(0.01) for c in active]
            dx -= min(b[0] for b in boxes)
            dy -= min(b[1] for b in boxes)
    return dx, dy


def pass_depths(surface: float, depth: float, step: float) -> list[float]:
    depth = abs(depth)
    if step <= 0 or step >= depth:
        return [surface - depth]
    n = math.ceil(depth / step - 1e-9)
    return [surface - min(k * step, depth) for k in range(1, n + 1)]


@dataclass
class KrlResult:
    name: str
    src: str
    dat: str
    cut_length: float = 0.0
    travel_length: float = 0.0
    est_time: float = 0.0
    motions: int = 0
    lines: int = 0
    warnings: list[str] = field(default_factory=list)


class _Gen:
    def __init__(self, contours: list[Contour], settings: Settings, source: str):
        self.s = settings
        self.g = settings.general
        self.contours = [c for c in contours if c.enabled]
        self.source = source
        self.name = sanitize_name(self.g.program_name)
        self.dx, self.dy = origin_shift(contours, settings)
        self.lines: list[str] = []
        self.indent = 0
        self.cur: tuple[float, float, float] | None = None
        self.vel_mm_min: float | None = None
        self.res = KrlResult(self.name, "", "")

    # ---- Ausgabehilfen -------------------------------------------------
    def w(self, text: str = "") -> None:
        self.lines.append(("  " * self.indent + text) if text else "")

    def tp(self, p: Point) -> Point:
        return (p[0] + self.dx, p[1] + self.dy)

    def pos(self, x: float, y: float, z: float) -> str:
        g = self.g
        return (f"{{X {fmt(x)},Y {fmt(y)},Z {fmt(z)},"
                f"A {fmt(g.a)},B {fmt(g.b)},C {fmt(g.c)}}}")

    def vel(self, mm_min: float) -> None:
        if self.vel_mm_min is not None and abs(self.vel_mm_min - mm_min) < 1e-9:
            return
        ms = mm_min / 60000.0
        if ms > VEL_CP_MAX:
            self.res.warnings.append(
                f"Bahngeschwindigkeit {mm_min:.0f} mm/min > {VEL_CP_MAX} m/s, auf {VEL_CP_MAX} m/s begrenzt.")
            ms = VEL_CP_MAX
        ms = max(ms, 0.0001)
        self.vel_mm_min = ms * 60000.0
        self.w(f"$VEL.CP = {fmt_short(round(ms, 6))}")

    def _account(self, length: float, cut: bool) -> None:
        if cut:
            self.res.cut_length += length
        else:
            self.res.travel_length += length
        if self.vel_mm_min:
            self.res.est_time += length / (self.vel_mm_min / 60.0)
        self.res.motions += 1

    def lin(self, x: float, y: float, z: float, apo: bool = False, cut: bool = False) -> None:
        if self.cur is not None:
            cx, cy, cz = self.cur
            if abs(cx - x) < 1e-4 and abs(cy - y) < 1e-4 and abs(cz - z) < 1e-4:
                return
            self._account(math.dist(self.cur, (x, y, z)), cut)
        self.w(f"LIN {self.pos(x, y, z)}{' C_DIS' if apo else ''}")
        self.cur = (x, y, z)

    def circ(self, arc: Arc, z: float, apo: bool) -> None:
        (ax, ay), (ex, ey) = self.tp(arc.mid), self.tp(arc.end)
        self.w(f"CIRC {self.pos(ax, ay, z)},{self.pos(ex, ey, z)}{' C_DIS' if apo else ''}")
        self._account(arc.length(), True)
        self.cur = (ex, ey, z)

    def path(self, c: Contour, z: float) -> None:
        """Kontur auf Höhe z abfahren; letzter Punkt Genauhalt."""
        moves: list[tuple[str, object]] = []
        for s in c.segments:
            if isinstance(s, Line):
                moves.append(("lin", s.end))
                continue
            n = max(1, math.ceil(abs(s.sweep) / MAX_CIRC_SWEEP - 1e-9))
            for piece in s.split(n):
                if dist(piece.start, piece.end) < MIN_CIRC_CHORD or piece.sagitta() < MIN_CIRC_SAGITTA:
                    moves.append(("lin", piece.end))
                else:
                    moves.append(("circ", piece))
        for k, (kind, obj) in enumerate(moves):
            apo = k < len(moves) - 1
            if kind == "lin":
                x, y = self.tp(obj)
                self.lin(x, y, z, apo=apo, cut=True)
            else:
                self.circ(obj, z, apo)

    def out(self, nr: int, state: bool) -> None:
        if nr > 0:
            self.w(f"$OUT[{nr}] = {'TRUE' if state else 'FALSE'}")

    # ---- Programmteile -------------------------------------------------
    def header(self) -> None:
        g = self.g
        prof = "Plasmaschneiden" if self.s.profile == "plasma" else "Fraesen"
        self.w("&ACCESS RVP")
        self.w("&REL 1")
        self.w(f"DEF {self.name}( )")
        self.w(";FOLD INI")
        self.w("  ;FOLD BASISTECH INI")
        self.w("    GLOBAL INTERRUPT DECL 3 WHEN $STOPMESS==TRUE DO IR_STOPM ( )")
        self.w("    INTERRUPT ON 3")
        self.w("    BAS (#INITMOV,0 )")
        self.w("  ;ENDFOLD (BASISTECH INI)")
        self.w(";ENDFOLD (INI)")
        self.w()
        self.w(f"; Erzeugt mit DXFtoKRL am {datetime.now():%d.%m.%Y %H:%M}")
        self.w(f"; Quelle: {ascii_text(os.path.basename(self.source))}")
        self.w(f"; Profil: {prof}, {len(self.contours)} Konturen")
        self.w("; Bahn = Werkzeugmitte (keine Radius-/Schnittspaltkorrektur)")
        self.w("; ERST IN T1 MIT REDUZIERTER GESCHWINDIGKEIT TESTEN!")
        self.w()
        self.w(";FOLD Einstellungen")
        self.indent += 1
        self.w(f"$BASE = BASE_DATA[{g.base_no}]")
        self.w(f"$TOOL = TOOL_DATA[{g.tool_no}]")
        self.w("$IPO_MODE = #BASE")
        self.w("$ORI_TYPE = #CONSTANT")
        self.w("$CIRC_TYPE = #BASE")
        self.w(f"$APO.CDIS = {fmt_short(g.apo_cdis)}")
        self.w("$ADVANCE = 3")
        self.w(f"BAS (#VEL_PTP,{int(g.ptp_vel)} )")
        self.indent -= 1
        self.w(";ENDFOLD")
        self.w()

    def safe_outputs_off(self) -> None:
        if self.s.profile == "plasma":
            p = self.s.plasma
            self.out(p.torch_out, False)
            self.out(p.thc_out, False)
        else:
            self.out(self.s.milling.spindle_out, False)

    def approach_first(self) -> None:
        g = self.g
        if g.use_home:
            self.w("PTP XHOME")
        if self.contours:
            x, y = self.tp(self.contours[0].start)
            self.w(f"PTP {self.pos(x, y, g.safe_z)}")
            self.cur = (x, y, g.safe_z)
        self.w()

    def footer(self) -> None:
        g = self.g
        self.w()
        if g.use_home:
            self.w("PTP XHOME")
        self.w("END")

    def milling(self) -> None:
        g, m = self.g, self.s.milling
        depths = pass_depths(g.surface_z, m.depth, m.step_down)
        if m.spindle_out:
            self.w("; Spindel ein")
            self.w("WAIT SEC 0")
            self.out(m.spindle_out, True)
            if m.spindle_delay > 0:
                self.w(f"WAIT SEC {fmt_short(m.spindle_delay)}")
            self.w()
        approach_z = g.surface_z + abs(m.approach)
        for i, c in enumerate(self.contours, 1):
            sx, sy = self.tp(c.start)
            ex, ey = self.tp(c.end)
            self.w(f";FOLD Kontur {i}: {ascii_text(c.describe())}")
            self.indent += 1
            self.vel(g.travel_speed)
            self.lin(sx, sy, g.safe_z)
            for k, z in enumerate(depths):
                if k > 0 and not c.closed:
                    self.vel(g.travel_speed)
                    self.lin(ex, ey, g.safe_z)
                    self.lin(sx, sy, g.safe_z)
                if k == 0 or not c.closed:
                    self.vel(g.travel_speed)
                    if approach_z < g.safe_z:
                        self.lin(sx, sy, approach_z)
                self.vel(m.plunge_feed)
                self.lin(sx, sy, z, cut=True)
                self.vel(m.feed)
                self.path(c, z)
            self.vel(g.travel_speed)
            self.lin(ex, ey, g.safe_z)
            self.indent -= 1
            self.w(";ENDFOLD")
        if m.spindle_out:
            self.w()
            self.w("; Spindel aus")
            self.w("WAIT SEC 0")
            self.out(m.spindle_out, False)

    def plasma(self) -> None:
        g, p = self.g, self.s.plasma
        pierce_z = g.surface_z + p.pierce_height
        cut_z = g.surface_z + p.cut_height
        if not p.torch_out:
            self.res.warnings.append("Kein Ausgang für den Brenner eingestellt – Brenner wird nicht geschaltet.")
        for i, c in enumerate(self.contours, 1):
            sx, sy = self.tp(c.start)
            ex, ey = self.tp(c.end)
            self.w(f";FOLD Kontur {i}: {ascii_text(c.describe())}")
            self.indent += 1
            self.vel(g.travel_speed)
            self.lin(sx, sy, g.safe_z)
            self.lin(sx, sy, pierce_z)
            self.w("ARC_ON( )")
            if p.pierce_delay > 0:
                self.w(f"WAIT SEC {fmt_short(p.pierce_delay)}")
            self.vel(p.plunge_feed)
            self.lin(sx, sy, cut_z, cut=True)
            if p.thc_out:
                self.w("WAIT SEC 0")
                self.out(p.thc_out, True)
            self.vel(p.feed)
            self.path(c, cut_z)
            if p.thc_out:
                self.w("WAIT SEC 0")
                self.out(p.thc_out, False)
            self.w("ARC_OFF( )")
            self.vel(g.travel_speed)
            self.lin(ex, ey, g.safe_z)
            self.indent -= 1
            self.w(";ENDFOLD")

    def plasma_subs(self) -> None:
        p = self.s.plasma
        self.w()
        self.w("DEF ARC_ON( )")
        self.indent += 1
        if not p.torch_out:
            self.w("; kein Brenner-Ausgang konfiguriert")
        elif p.arc_ok_in:
            t = p.timer_no
            self.w("DECL BOOL ok")
            self.w("ok = FALSE")
            self.w("WHILE NOT ok")
            self.indent += 1
            self.w("WAIT SEC 0")
            self.out(p.torch_out, True)
            self.w(f"$TIMER_STOP[{t}] = TRUE")
            self.w(f"$TIMER[{t}] = {-int(round(p.arc_timeout * 1000))}")
            self.w(f"$TIMER_STOP[{t}] = FALSE")
            self.w(f"WAIT FOR $IN[{p.arc_ok_in}] OR $TIMER_FLAG[{t}]")
            self.w(f"$TIMER_STOP[{t}] = TRUE")
            self.w(f"IF $IN[{p.arc_ok_in}] THEN")
            self.w("  ok = TRUE")
            self.w("ELSE")
            self.indent += 1
            self.out(p.torch_out, False)
            self.w("; Zuendung fehlgeschlagen. Ursache beheben, dann Start = neuer Versuch")
            self.w("HALT")
            self.indent -= 1
            self.w("ENDIF")
            self.indent -= 1
            self.w("ENDWHILE")
        else:
            self.w("WAIT SEC 0")
            self.out(p.torch_out, True)
        self.indent -= 1
        self.w("END")
        self.w()
        self.w("DEF ARC_OFF( )")
        self.indent += 1
        self.w("WAIT SEC 0")
        self.out(p.torch_out, False)
        if p.post_delay > 0:
            self.w(f"WAIT SEC {fmt_short(p.post_delay)}")
        self.indent -= 1
        self.w("END")

    def dat(self) -> str:
        return "\n".join([
            "&ACCESS RVP",
            "&REL 1",
            f"DEFDAT  {self.name}",
            ";FOLD EXTERNAL DECLARATIONS",
            ";FOLD BAS EXT",
            "EXT  BAS (BAS_COMMAND  :IN,REAL  :IN )",
            "DECL INT SUCCESS",
            ";ENDFOLD (BAS EXT)",
            ";ENDFOLD (EXTERNAL DECLARATIONS)",
            "ENDDAT",
            "",
        ])

    def run(self) -> KrlResult:
        self.header()
        self.safe_outputs_off()
        self.approach_first()
        if self.s.profile == "plasma":
            self.plasma()
        else:
            self.milling()
        self.footer()
        if self.s.profile == "plasma":
            self.plasma_subs()
        self.lines.append("")
        self.res.src = "\n".join(self.lines)
        self.res.dat = self.dat()
        self.res.lines = len(self.lines)
        if not self.contours:
            self.res.warnings.append("Keine aktiven Konturen – Programm enthält keine Bahn.")
        if self.g.safe_z <= self.g.surface_z:
            self.res.warnings.append("Sicherheitshöhe liegt nicht über der Werkstückoberfläche!")
        # Warnungen nur einmal
        self.res.warnings = list(dict.fromkeys(self.res.warnings))
        return self.res


def generate(contours: list[Contour], settings: Settings, source: str = "") -> KrlResult:
    return _Gen(contours, settings, source).run()


def write_files(result: KrlResult, directory: str) -> tuple[str, str]:
    """Schreibt NAME.src / NAME.dat mit Windows-Zeilenenden (KR C2)."""
    src_path = os.path.join(directory, result.name + ".src")
    dat_path = os.path.join(directory, result.name + ".dat")
    for path, text in ((src_path, result.src), (dat_path, result.dat)):
        with open(path, "wb") as fh:
            fh.write(text.replace("\n", "\r\n").encode("cp1252", errors="replace"))
    return src_path, dat_path
