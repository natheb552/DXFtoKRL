import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from dxftokrl.gui.main_window import MainWindow  # noqa: E402
from dxftokrl.settings import Settings  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "beispiel.dxf")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_gui_load_and_edit(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    w = MainWindow(Settings())
    w.load_dxf(EXAMPLE)
    assert len(w.contours) == 7
    assert "CIRC" in w.src_view.toPlainText()
    w.profile_box.setCurrentIndex(1)
    assert "Fraesen" in w.result.src
    w.contour_list.setCurrentRow(3)
    w.reverse_contour()
    w.move_contour(-1)
    w.optimize()
    assert len(w.contours) == 7
    w.close()
