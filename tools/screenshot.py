"""Offscreen-Test: GUI starten, DXF laden, Screenshot speichern."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PySide6.QtWidgets import QApplication  # noqa: E402

from dxftokrl.gui.main_window import MainWindow  # noqa: E402
from dxftokrl.settings import Settings  # noqa: E402

app = QApplication([])
w = MainWindow(Settings())
w.resize(1400, 850)
w.show()
w.load_dxf(sys.argv[1])
w.contour_list.setCurrentRow(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
for _ in range(5):
    app.processEvents()
w.preview.fit()
app.processEvents()
w.grab().save(sys.argv[2])
print(w.status.text())
