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


def test_automation_test_settings_are_saved_to_snapshot(qapp) -> None:
    original = AppConfig()
    dialog = SettingsDialog(original, automation_test=True)
    dialog.automation_main_title.setText("ParkMatik Test")
    dialog.automation_ticket_title.setText("Bilet Sorgulama Test")
    dialog.automation_click_x.setValue(0.61)
    dialog.automation_timeout.setValue(9)
    dialog._save()

    assert original.automation.main_window_title_contains == "ParkMatik"
    assert original.automation.ticket_window_title_contains == "Bilet Sorgulama"
    assert dialog.config.automation.main_window_title_contains == "ParkMatik Test"
    assert dialog.config.automation.ticket_window_title_contains == "Bilet Sorgulama Test"
    assert dialog.config.automation.ticket_row_click_x == 0.61
    assert dialog.config.automation.timeout_seconds == 9
