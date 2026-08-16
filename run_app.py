"""PyInstaller-safe entry point for the PTS Plate OCR tray application.

Keeping this file outside the package means PyInstaller imports the real
application module as ``pts_plate_ocr.app``.  Its relative imports then retain
their package context in the frozen executable.
"""

from pts_plate_ocr.app import main


if __name__ == "__main__":
    raise SystemExit(main())
