from __future__ import annotations

import logging
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from .capture import CaptureError, CaptureFrame, capture_frame
from .config import APP_NAME, AppConfig, ConfigStore, app_data_dir
from .diagnostics import Diagnostics
from .hotkey import HotkeyListener
from .logging_setup import configure_logging
from .models import RecognitionResult, ResultStatus
from .ocr import LocalPlateOcr
from .plate import clean_ocr_text
from .ui import CalibrationController, ResultPopup, SettingsDialog
from .windows import enable_dpi_awareness

LOGGER = logging.getLogger(__name__)


class ScanWorker(QtCore.QObject):
    completed = QtCore.Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.ocr = LocalPlateOcr()

    @QtCore.Slot(object)
    def scan(self, config: AppConfig) -> None:
        try:
            frame = capture_frame(config)
            result = self.ocr.analyze(frame.search_band, config.confidence)
            self.completed.emit(result, frame)
        except CaptureError as error:
            self.completed.emit(RecognitionResult(ResultStatus.ERROR, message=str(error)), None)
        except Exception as error:
            LOGGER.exception("Unexpected scan failure")
            self.completed.emit(RecognitionResult(ResultStatus.ERROR, message=f"Beklenmeyen hata: {error}"), None)

class ApplicationController(QtCore.QObject):
    scan_requested = QtCore.Signal(object)

    def __init__(self, app: QtWidgets.QApplication) -> None:
        super().__init__()
        self.app = app
        self.data_app_name = APP_NAME
        self.store = ConfigStore(app_name=self.data_app_name)
        self.config = self.store.load()
        self.busy = False
        self.popup = ResultPopup()
        self.popup.copy_requested.connect(self.copy_to_clipboard)
        self.hotkey = HotkeyListener()
        self.hotkey.activated.connect(self.request_scan)
        self.worker_thread = QtCore.QThread(self)
        self.worker = ScanWorker()
        self.worker.moveToThread(self.worker_thread)
        self.scan_requested.connect(self.worker.scan, QtCore.Qt.ConnectionType.QueuedConnection)
        self.worker.completed.connect(self._scan_completed)
        self.worker_thread.start()
        self.calibration = CalibrationController(self.store, self.config)
        self.calibration.updated.connect(self._calibration_saved)
        self.calibration.message.connect(self.notify)
        self.tray = self._create_tray()
        self._register_hotkey()

    def _create_tray(self) -> QtWidgets.QSystemTrayIcon:
        icon = self.app.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
        tray = QtWidgets.QSystemTrayIcon(icon, self.app)
        menu = QtWidgets.QMenu()
        scan_action = menu.addAction("Şimdi tara")
        scan_action.triggered.connect(self.request_scan)
        calibrate_action = menu.addAction("Fotoğraf / plaka alanını kalibre et")
        calibrate_action.triggered.connect(self.calibration.start)
        settings_action = menu.addAction("Ayarlar")
        settings_action.triggered.connect(self.open_settings)
        logs_action = menu.addAction("Log klasörünü aç")
        logs_action.triggered.connect(self.open_logs)
        menu.addSeparator()
        quit_action = menu.addAction("Çıkış")
        quit_action.triggered.connect(self.shutdown)
        tray.setContextMenu(menu)
        tray.setToolTip(f"PTS Plaka OCR — {self.config.hotkey} ile tara")
        tray.show()
        return tray

    def _register_hotkey(self) -> None:
        try:
            self.hotkey.register(self.config.hotkey)
            self.tray.setToolTip(f"PTS Plaka OCR — {self.config.hotkey} ile tara")
        except (RuntimeError, ValueError) as error:
            LOGGER.warning("Hotkey registration failed: %s", error)
            self.notify(f"Kısayol kaydedilemedi: {error}")


    def _calibration_saved(self, config: AppConfig) -> None:
        self.config = config
        self.calibration.config = config
        self.tray.setToolTip(f"PTS Plaka OCR — {self.config.hotkey} ile tara")

    def _apply_settings(self, candidate: AppConfig) -> None:
        previous = self.config
        if candidate.hotkey != previous.hotkey:
            self.hotkey.unregister()
            try:
                self.hotkey.register(candidate.hotkey)
            except (RuntimeError, ValueError) as error:
                LOGGER.warning("Hotkey update failed: %s", error)
                try:
                    self.hotkey.register(previous.hotkey)
                except (RuntimeError, ValueError) as restore_error:
                    LOGGER.error("Could not restore previous hotkey: %s", restore_error)
                self.notify(f"Kısayol kaydedilemedi: {error}. Önceki ayar korundu.")
                return
        self.config = candidate
        self.calibration.config = candidate
        self.store.save(self.config)
        self.tray.setToolTip(f"PTS Plaka OCR — {self.config.hotkey} ile tara")
        self.notify(f"Ayarlar kaydedildi. OCR kısayolu: {self.config.hotkey}")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config)
        dialog.saved.connect(self._apply_settings)
        dialog.exec()

    def open_logs(self) -> None:
        path = app_data_dir(self.data_app_name) / "logs"
        path.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    @QtCore.Slot()
    def request_scan(self) -> None:
        if self.busy:
            self.notify("OCR işlemi zaten sürüyor.")
            return
        self.busy = True
        self.tray.showMessage("PTS Plaka OCR", "Görünen fotoğraf alanı okunuyor…", QtWidgets.QSystemTrayIcon.MessageIcon.Information, 1500)
        self.scan_requested.emit(self.config)

    @QtCore.Slot(object, object)
    def _scan_completed(self, result: RecognitionResult, frame: CaptureFrame | None) -> None:
        self.busy = False
        if frame is not None:
            Diagnostics(self.config, app_name=self.data_app_name).record(frame.photo, frame.search_band, result)
        if result.status == ResultStatus.HIGH_CONFIDENCE and result.plate:
            self.copy_to_clipboard(result.plate, notify=False)
        self.popup.present(result, self.config.popup_timeout_seconds)
        if result.status == ResultStatus.ERROR:
            self.notify(result.message)

    @QtCore.Slot(str)
    def copy_to_clipboard(self, plate: str, notify: bool = True) -> None:
        text = clean_ocr_text(plate)
        if not text:
            return
        self.app.clipboard().setText(text)
        if notify:
            self.notify(f"{text} panoya kopyalandı.")
        self.popup.hide()

    def notify(self, message: str) -> None:
        self.tray.showMessage("PTS Plaka OCR", message, QtWidgets.QSystemTrayIcon.MessageIcon.Information, 3500)

    def shutdown(self) -> None:
        self.hotkey.unregister()
        self.worker_thread.quit()
        self.worker_thread.wait(3000)
        self.tray.hide()
        self.app.quit()


def main() -> int:
    if sys.platform != "win32":
        print("PTS Plaka OCR yalnız Windows'ta çalışır.", file=sys.stderr)
        return 2
    enable_dpi_awareness()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("PTS Plaka OCR")
    app.setQuitOnLastWindowClosed(False)
    configure_logging()
    controller = ApplicationController(app)
    app.aboutToQuit.connect(controller.hotkey.unregister)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
