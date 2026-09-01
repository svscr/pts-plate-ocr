from PySide6 import QtGui

from pts_plate_ocr.config import AppConfig
from pts_plate_ocr.ui import SettingsDialog


def test_settings_edits_an_independent_config_snapshot(qapp) -> None:
    original = AppConfig(hotkey="Ctrl+Alt+P")
    dialog = SettingsDialog(original)
    dialog.hotkey.setKeySequence(QtGui.QKeySequence("Ctrl+Alt+O"))
    dialog._save()
    assert original.hotkey == "Ctrl+Alt+P"
    assert dialog.config.hotkey == "Ctrl+Alt+O"
