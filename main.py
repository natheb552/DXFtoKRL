"""Startskript (auch für PyInstaller)."""
import sys

from dxftokrl.app import main

if __name__ == "__main__":
    sys.exit(main())
