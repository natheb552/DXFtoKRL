"""Erzeugt examples/beispiel.dxf: Platte mit Bohrungen, Langloch, Spline und Gravur-Layer."""
import os
import sys

import ezdxf

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "examples", "beispiel.dxf")

doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 4  # mm
doc.layers.add("AUSSEN", color=1)
doc.layers.add("INNEN", color=3)
doc.layers.add("GRAVUR", color=5)
msp = doc.modelspace()

# Außenkontur 200x120 mit abgerundeten Ecken (R10) als Polylinie mit Bulges
b = 0.41421356  # tan(90°/4)
msp.add_lwpolyline([(10, 0, 0), (190, 0, b), (200, 10, 0), (200, 110, b), (190, 120, 0),
                    (10, 120, b), (0, 110, 0), (0, 10, b)], format="xyb", close=True,
                   dxfattribs={"layer": "AUSSEN"})

# Bohrungen
for x, y in ((20, 20), (180, 20), (180, 100), (20, 100)):
    msp.add_circle((x, y), 5, dxfattribs={"layer": "INNEN"})

# Langloch aus Einzellinien und Bögen (absichtlich unsortiert)
msp.add_line((70, 60), (130, 60), dxfattribs={"layer": "INNEN"})
msp.add_arc((130, 70), 10, 270, 90, dxfattribs={"layer": "INNEN"})
msp.add_line((70, 80), (130, 80), dxfattribs={"layer": "INNEN"})
msp.add_arc((70, 70), 10, 90, 270, dxfattribs={"layer": "INNEN"})

# Offene Welle als Spline (Gravur)
msp.add_spline([(40, 30), (60, 45), (80, 25), (100, 45), (120, 25), (140, 45), (160, 30)],
               dxfattribs={"layer": "GRAVUR"})

doc.saveas(out)
print("geschrieben:", os.path.abspath(out))
