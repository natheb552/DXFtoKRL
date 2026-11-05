import math
import re

import ezdxf
import pytest

from dxftokrl.dxf_import import load_dxf
from dxftokrl.geometry import Arc, Contour, Line, TAU, arc_from_points, dist
from dxftokrl.krl import generate, pass_depths, sanitize_name, write_files
from dxftokrl.paths import chain_segments, optimize_order
from dxftokrl.settings import Settings


# ---------- Geometrie ----------

def test_arc_from_points_ccw_and_cw():
    a = arc_from_points((1, 0), (0, 1), (-1, 0))
    assert isinstance(a, Arc)
    assert a.center == pytest.approx((0, 0), abs=1e-9)
    assert a.sweep == pytest.approx(math.pi)
    b = arc_from_points((-1, 0), (0, 1), (1, 0))
    assert b.sweep == pytest.approx(-math.pi)
    assert b.end == pytest.approx((1, 0), abs=1e-9)


def test_collinear_gives_line():
    assert isinstance(arc_from_points((0, 0), (1, 1e-12), (2, 0)), Line)


def test_contour_reverse_and_area():
    sq = Contour([Line((0, 0), (10, 0)), Line((10, 0), (10, 10)),
                  Line((10, 10), (0, 10)), Line((0, 10), (0, 0))], closed=True)
    assert sq.signed_area() == pytest.approx(100)
    assert sq.reversed().signed_area() == pytest.approx(-100)


# ---------- Verketten / Reihenfolge ----------

def test_chain_unsorted_and_reversed_segments():
    segs = [("L", Line((10, 10), (10, 0))), ("L", Line((0, 0), (10, 0))),
            ("L", Line((0, 10), (10, 10))), ("L", Line((0, 0), (0, 10.01)))]
    cs = chain_segments(segs, tol=0.05)
    assert len(cs) == 1 and cs[0].closed and len(cs[0].segments) == 4
    for a, b in zip(cs[0].segments, cs[0].segments[1:]):
        assert dist(a.end, b.start) <= 0.05


def test_chain_keeps_layers_apart():
    segs = [("A", Line((0, 0), (1, 0))), ("B", Line((1, 0), (2, 0)))]
    assert len(chain_segments(segs)) == 2


def test_optimize_reverses_open_and_moves_circle_start():
    far = Contour([Line((100, 0), (50, 0))], "L")
    circ = Contour([Arc((10, 0), 5, math.pi / 2, TAU)], "L", closed=True)
    order = optimize_order([far, circ], start=(0, 0))
    assert order[0].segments[0].center == (10, 0)
    assert order[0].start == pytest.approx((5, 0), abs=1e-9)
    assert order[1].start == (50, 0)  # offene Kontur umgedreht


# ---------- DXF ----------

@pytest.fixture
def sample(tmp_path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0, 0), (50, 0, 1), (50, 20, 0), (0, 20, 0)], format="xyb",
                       close=True, dxfattribs={"layer": "A"})
    msp.add_circle((25, 10), 3, dxfattribs={"layer": "B"})
    msp.add_arc((0, 0), 10, 0, 90, dxfattribs={"layer": "C", "extrusion": (0, 0, -1)})
    msp.add_text("Hallo")
    blk = doc.blocks.new("LOCH")
    blk.add_circle((0, 0), 2)
    msp.add_blockref("LOCH", (80, 10), dxfattribs={"layer": "B"})
    p = tmp_path / "t.dxf"
    doc.saveas(p)
    return str(p)


def test_import(sample):
    r = load_dxf(sample)
    assert r.layer_counts["A"] == 4      # 3 Linien + 1 Bogen
    assert r.layer_counts["B"] == 2      # Kreis + Kreis aus Block (Layer 0 -> B)
    assert r.skipped["TEXT"] == 1
    arcs = [s for l, s in r.segments if l == "A" and isinstance(s, Arc)]
    assert arcs[0].start == pytest.approx((50, 0), abs=1e-6)
    assert arcs[0].end == pytest.approx((50, 20), abs=1e-6)
    # gespiegelter Bogen (Extrusion -Z): Punkte liegen bei x<=0
    c = [s for l, s in r.segments if l == "C"][0]
    assert {round(c.start[0], 6), round(c.end[0], 6)} == {-10.0, 0.0}


def test_inch_units(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 1
    doc.modelspace().add_line((0, 0), (1, 0))
    p = tmp_path / "in.dxf"
    doc.saveas(p)
    r = load_dxf(str(p))
    assert r.segments[0][1].length() == pytest.approx(25.4)


# ---------- KRL ----------

def _krl(sample, profile):
    r = load_dxf(sample)
    cs = optimize_order(chain_segments(r.segments))
    s = Settings(profile=profile)
    s.plasma.torch_out = 10
    s.plasma.arc_ok_in = 12
    s.plasma.thc_out = 11
    s.milling.spindle_out = 5
    return generate(cs, s, sample)


def _balanced(src):
    defs = len(re.findall(r"^\s*DEF ", src, re.M))
    ends = len(re.findall(r"^\s*END\s*$", src, re.M))
    folds = len(re.findall(r"^\s*;FOLD", src, re.M))
    endfolds = len(re.findall(r"^\s*;ENDFOLD", src, re.M))
    return defs == ends and folds == endfolds


@pytest.mark.parametrize("profile", ["plasma", "milling"])
def test_krl_structure(sample, profile):
    res = _krl(sample, profile)
    src = res.src
    assert _balanced(src)
    assert src.startswith("&ACCESS RVP")
    assert "BAS (#INITMOV,0 )" in src
    assert "$BASE = BASE_DATA[1]" in src
    assert "CIRC {" in src
    assert all(ord(ch) < 128 for ch in src)
    # jede Bewegungszeile hat vollständige Koordinaten
    for line in src.splitlines():
        if line.strip().startswith(("LIN ", "PTP {")):
            assert re.search(r"\{X -?\d+\.\d{3},Y -?\d+\.\d{3},Z -?\d+\.\d{3},A", line), line
    assert res.cut_length > 0 and res.est_time > 0


def test_plasma_sequence(sample):
    src = _krl(sample, "plasma").src
    assert "DEF ARC_ON( )" in src and "WAIT FOR $IN[12] OR $TIMER_FLAG[1]" in src
    on = src.index("ARC_ON( )\n", src.index(";FOLD Kontur 1"))
    thc = src.index("$OUT[11] = TRUE")
    off = src.index("ARC_OFF( )", on)
    assert on < thc < off


def test_milling_passes():
    assert pass_depths(0, 2.5, 1) == [-1, -2, -2.5]
    assert pass_depths(0, 2, 0) == [-2]


def test_full_circle_split_into_circs():
    s = Settings(profile="milling")
    s.milling.depth, s.milling.step_down = 1, 0
    c = Contour([Arc((0, 0), 10, 0, TAU)], "L", closed=True)
    src = generate([c], s).src
    assert src.count("CIRC {") == 3


def test_sanitize_name():
    assert sanitize_name("Teil 1-ä") == "Teil_1_ae"
    assert sanitize_name("1abc")[0] == "P"
    assert len(sanitize_name("x" * 40)) == 24


def test_write_files_crlf(sample, tmp_path):
    res = _krl(sample, "plasma")
    src_path, dat_path = write_files(res, str(tmp_path))
    data = open(src_path, "rb").read()
    assert b"\r\n" in data and b"\r\r" not in data
    assert open(dat_path, "rb").read().startswith(b"&ACCESS RVP\r\n")
