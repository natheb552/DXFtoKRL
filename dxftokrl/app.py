"""Programmstart."""
import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow
from .settings import load_settings


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DXFtoKRL")
    win = MainWindow(load_settings())
    win.show()
    if len(sys.argv) > 1:
        win.load_dxf(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
