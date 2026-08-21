from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .config import AppConfig, ConfigStore
from .models import NormalizedRect, PixelRect, RecognitionResult, ResultStatus, WindowMatcher
from .shortcuts import normalize_hotkey
from .windows import WindowInfo, find_window, foreground_window_info


class SelectionOverlay(QtWidgets.QWidget):
    selected = QtCore.Signal(QtCore.QRect)
    cancelled = QtCore.Signal()

    def __init__(self, instruction: str) -> None:
        super().__init__()
        self.instruction = instruction
        self.origin: QtCore.QPoint | None = None
        self.selection = QtCore.QRect()
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        screen = QtGui.QGuiApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        self.activateWindow()
        super().showEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.selection = QtCore.QRect(self.origin, self.origin)
            self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self.origin is not None:
            self.selection = QtCore.QRect(self.origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.selection.width() > 20 and self.selection.height() > 20:
            global_selection = self.selection.translated(self.geometry().topLeft())
            self.selected.emit(global_selection)
            self.close()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 100))
        painter.setPen(QtGui.QPen(QtGui.QColor("#30d5c8"), 2))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        if not self.selection.isNull():
            painter.drawRect(self.selection)
        painter.setPen(QtGui.QColor("white"))
        painter.setFont(QtGui.QFont("Segoe UI", 13, QtGui.QFont.Weight.Bold))
        painter.drawText(24, 38, self.instruction)
        painter.setFont(QtGui.QFont("Segoe UI", 10))
        painter.drawText(24, 62, "Fareyle sürükleyin. İptal için Esc.")


def _normalise(inner: QtCore.QRect, outer: PixelRect) -> NormalizedRect:
    rect = NormalizedRect(
        left=(inner.left() - outer.left) / outer.width,
        top=(inner.top() - outer.top) / outer.height,
        width=inner.width() / outer.width,
        height=inner.height() / outer.height,
    )
    rect.validate()
    return rect


class CalibrationController(QtCore.QObject):
    updated = QtCore.Signal(AppConfig)
    message = QtCore.Signal(str)

    def __init__(self, store: ConfigStore, config: AppConfig) -> None:
        super().__init__()
        self.store = store
        self.config = config
        self._target: WindowInfo | None = None
        self._photo: QtCore.QRect | None = None
        self._overlay: SelectionOverlay | None = None

    def start(self) -> None:
        self._target = foreground_window_info()
        self._photo = None
        self._overlay = SelectionOverlay("1/2: PTS araç fotoğrafının tamamını seçin")
        self._overlay.selected.connect(self._photo_selected)
        self._overlay.cancelled.connect(lambda: self.message.emit("Kalibrasyon iptal edildi."))
        self._overlay.show()

    def _photo_selected(self, rect: QtCore.QRect) -> None:
        self._photo = rect
        self._overlay = SelectionOverlay("2/2: Plakanın gelebileceği geniş arama bandını seçin")
        self._overlay.selected.connect(self._search_selected)
        self._overlay.cancelled.connect(lambda: self.message.emit("Kalibrasyon iptal edildi."))
        self._overlay.show()

    def _search_selected(self, rect: QtCore.QRect) -> None:
        if self._photo is None:
            return
        search = rect.intersected(self._photo)
        if search.width() < 20 or search.height() < 20:
            self.message.emit("Arama bandı fotoğraf alanının içinde olmalı.")
            return
        photo_pixels = PixelRect(self._photo.left(), self._photo.top(), self._photo.width(), self._photo.height())
        self.config.plate_search_roi = _normalise(search, photo_pixels)
        target = self._target
        if target:
            client = PixelRect(target.client_left, target.client_top, target.client_width, target.client_height)
            photo_inside_window = (
                self._photo.left() >= client.left
                and self._photo.top() >= client.top
                and self._photo.right() <= client.right
                and self._photo.bottom() <= client.bottom
            )
            if photo_inside_window and target.title:
                self.config.photo_roi_relative_to_window = _normalise(self._photo, client)
                # PID is deliberately not persisted: PTS may restart between shifts.
                self.config.window_matcher = WindowMatcher(title_contains=target.title, process_id=None)
            else:
                self.config.photo_roi_relative_to_window = None
                self.config.window_matcher = None
                screen = QtGui.QGuiApplication.primaryScreen().geometry()
                self.config.desktop_photo_roi = _normalise(
                    self._photo,
                    PixelRect(screen.left(), screen.top(), screen.width(), screen.height()),
                )
        else:
            screen = QtGui.QGuiApplication.primaryScreen().geometry()
            self.config.desktop_photo_roi = _normalise(
                self._photo,
                PixelRect(screen.left(), screen.top(), screen.width(), screen.height()),
            )
            self.config.photo_roi_relative_to_window = None
            self.config.window_matcher = None
        self.store.save(self.config)
        self.updated.emit(self.config)
        self.message.emit(f"Kalibrasyon kaydedildi. {self.config.hotkey} ile deneyebilirsiniz.")


class AutomationCalibrationController(QtCore.QObject):
    """Keeps test-automation coordinates separate from normal OCR calibration."""

    updated = QtCore.Signal(AppConfig)
    message = QtCore.Signal(str)

    def __init__(self, store: ConfigStore, config: AppConfig) -> None:
        super().__init__()
        self.store = store
        self.config = config
        self._target: WindowInfo | None = None
        self._photo: QtCore.QRect | None = None
        self._overlay: SelectionOverlay | None = None

    def start_ticket_grid(self) -> None:
        target = find_window(self.config.automation.ticket_window_title_contains)
        if target is None:
            self.message.emit("Bilet Sorgulama penceresi bulunamadı. Önce pencere başlığını ayarlayın.")
            return
        self._target = target
        self._overlay = SelectionOverlay("PTS otomasyonu: Bilet Sorgulama tablosunun tamamını seçin")
        self._overlay.selected.connect(self._ticket_grid_selected)
        self._overlay.cancelled.connect(lambda: self.message.emit("Otomasyon kalibrasyonu iptal edildi."))
        self._overlay.show()

    def start_entrance_photo(self) -> None:
        target = find_window(self.config.automation.image_dialog_title_contains)
        if target is None:
            self.message.emit("Önce ParkMatik'te Bilet Resimleri penceresini açın.")
            return
        self._target = target
        self._photo = None
        self._overlay = SelectionOverlay("PTS otomasyonu: Yalnız GİRİŞ fotoğraf alanını seçin")
        self._overlay.selected.connect(self._entrance_photo_selected)
        self._overlay.cancelled.connect(lambda: self.message.emit("Otomasyon kalibrasyonu iptal edildi."))
        self._overlay.show()

    def start_plate_input(self) -> None:
        target = find_window(self.config.automation.plate_dialog_title_contains)
        if target is None:
            self.message.emit("Önce ParkMatik'te Plaka Değiştirme penceresini açın.")
            return
        self._target = target
        self._overlay = SelectionOverlay("PTS otomasyonu: Plaka yazı alanını seçin")
        self._overlay.selected.connect(self._plate_input_selected)
        self._overlay.cancelled.connect(lambda: self.message.emit("Otomasyon kalibrasyonu iptal edildi."))
        self._overlay.show()

    def _ticket_grid_selected(self, rect: QtCore.QRect) -> None:
        if not self._target:
            return
        client = PixelRect(
            self._target.client_left,
            self._target.client_top,
            self._target.client_width,
            self._target.client_height,
        )
        try:
            self.config.automation.ticket_grid_roi = _normalise(rect, client)
        except ValueError:
            self.message.emit("Bilet tablosu PTS pencere sınırları içinde olmalı.")
            return
        self._save("Bilet tablosu kalibrasyonu kaydedildi.")

    def _entrance_photo_selected(self, rect: QtCore.QRect) -> None:
        self._photo = rect
        self._overlay = SelectionOverlay("PTS otomasyonu: Plakanın gelebileceği GİRİŞ arama bandını seçin")
        self._overlay.selected.connect(self._entrance_search_selected)
        self._overlay.cancelled.connect(lambda: self.message.emit("Otomasyon kalibrasyonu iptal edildi."))
        self._overlay.show()

    def _entrance_search_selected(self, rect: QtCore.QRect) -> None:
        if not self._target or not self._photo:
            return
        client = PixelRect(
            self._target.client_left,
            self._target.client_top,
            self._target.client_width,
            self._target.client_height,
        )
        search = rect.intersected(self._photo)
        if search.width() < 20 or search.height() < 20:
            self.message.emit("Arama bandı GİRİŞ fotoğraf alanının içinde olmalı.")
            return
        try:
            photo_pixels = PixelRect(
                self._photo.left(), self._photo.top(), self._photo.width(), self._photo.height()
            )
            self.config.automation.entrance_photo_roi = _normalise(self._photo, client)
            self.config.automation.entrance_plate_search_roi = _normalise(search, photo_pixels)
        except ValueError:
            self.message.emit("GİRİŞ fotoğrafı Bilet Resimleri pencere sınırları içinde olmalı.")
            return
        self._save("GİRİŞ görseli ve arama bandı kalibrasyonu kaydedildi.")

    def _plate_input_selected(self, rect: QtCore.QRect) -> None:
        if not self._target:
            return
        client = PixelRect(
            self._target.client_left,
            self._target.client_top,
            self._target.client_width,
            self._target.client_height,
        )
        try:
            self.config.automation.plate_input_roi = _normalise(rect, client)
        except ValueError:
            self.message.emit("Plaka alanı Plaka Değiştirme penceresinin içinde olmalı.")
            return
        self._save("Plaka alanı kalibrasyonu kaydedildi.")

    def _save(self, message: str) -> None:
        self.config.validate()
        self.store.save(self.config)
        self.updated.emit(self.config)
        self.message.emit(message)


class ResultPopup(QtWidgets.QWidget):
    copy_requested = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setStyleSheet(
            "QWidget { background: #20242b; color: #f4f7fb; border-radius: 10px; }"
            "QLineEdit, QComboBox { background: #11151b; border: 1px solid #4d5a6d; border-radius: 5px; padding: 6px; }"
            "QPushButton { background: #087f76; border: none; border-radius: 5px; padding: 7px 12px; }"
            "QPushButton:hover { background: #0aa395; }"
        )
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel("Plaka sonucu")
        self.heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.plate_edit = QtWidgets.QLineEdit()
        self.plate_edit.setPlaceholderText("Plaka bulunamadı")
        self.confidence = QtWidgets.QLabel()
        self.message = QtWidgets.QLabel()
        self.alternatives = QtWidgets.QComboBox()
        self.alternatives.currentTextChanged.connect(self._alternative_changed)
        copy_button = QtWidgets.QPushButton("Panoya kopyala")
        copy_button.clicked.connect(lambda: self.copy_requested.emit(self.plate_edit.text()))
        layout.addWidget(self.heading)
        layout.addWidget(self.plate_edit)
        layout.addWidget(self.confidence)
        layout.addWidget(self.alternatives)
        layout.addWidget(self.message)
        layout.addWidget(copy_button)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def _alternative_changed(self, text: str) -> None:
        if text:
            self.plate_edit.setText(text)

    def present(self, result: RecognitionResult, timeout_seconds: int) -> None:
        self._timer.stop()
        self.plate_edit.setText(result.plate or "")
        self.confidence.setText(f"Güven skoru: {round(result.score * 100)} / 100")
        self.message.setText(result.message)
        self.alternatives.blockSignals(True)
        self.alternatives.clear()
        self.alternatives.addItems([candidate.plate for candidate in result.candidates])
        self.alternatives.setVisible(len(result.candidates) > 1)
        self.alternatives.blockSignals(False)
        if result.status == ResultStatus.HIGH_CONFIDENCE:
            self.heading.setText("Yüksek güvenli plaka")
        elif result.status == ResultStatus.REVIEW:
            self.heading.setText("Lütfen sonucu kontrol edin")
        else:
            self.heading.setText("OCR sonucu")
        self.adjustSize()
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        # ParkMatik'in supplied 1920x1080 layout has a clear space below the
        # image dialog around 27.3% of the screen width. Keep the existing
        # bottom alignment while placing the result panel in that space.
        self.move(
            screen.left() + round(screen.width() * 0.273),
            screen.bottom() - self.height() - 64,
        )
        self.show()
        self.raise_()
        if result.status == ResultStatus.HIGH_CONFIDENCE:
            self._timer.start(timeout_seconds * 1000)


class SettingsDialog(QtWidgets.QDialog):
    saved = QtCore.Signal(AppConfig)

    def __init__(
        self,
        config: AppConfig,
        parent: QtWidgets.QWidget | None = None,
        *,
        automation_test: bool = False,
    ) -> None:
        super().__init__(parent)
        self.config = AppConfig.from_dict(config.to_dict())
        self.automation_test = automation_test
        self.setWindowTitle("PTS Plaka OCR Ayarları")
        layout = QtWidgets.QFormLayout(self)
        self.hotkey = QtWidgets.QKeySequenceEdit(self)
        self.hotkey.setClearButtonEnabled(True)
        self.hotkey.setMaximumSequenceLength(1)
        sequence = QtGui.QKeySequence.fromString(
            config.hotkey, QtGui.QKeySequence.SequenceFormat.PortableText
        )
        self.hotkey.setKeySequence(sequence)
        self.debug = QtWidgets.QCheckBox("Hata ayıklama görüntülerini yerelde sakla")
        self.debug.setChecked(config.debug.enabled)
        shortcut_note = QtWidgets.QLabel(
            "Kutuya tıklayıp kombinasyona basın. Öneri: Ctrl+Alt+P. "
            "A-Z, 0-9, Space ve F1-F24 desteklenir; harf/rakam için Ctrl, Alt veya Shift gerekir."
        )
        shortcut_note.setWordWrap(True)
        note = QtWidgets.QLabel("Varsayılan ön ayar: ParkMatik 1920×1080 ekran görüntüsü. Yerleşim değişirse yeniden kalibrasyon yapın.")
        note.setWordWrap(True)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow("OCR kısayolu", self.hotkey)
        layout.addRow(shortcut_note)
        layout.addRow("Tanılama", self.debug)
        if self.automation_test:
            self.automation_enabled = QtWidgets.QCheckBox("PTS otomasyonu test modunda açık")
            self.automation_enabled.setChecked(config.automation.enabled)
            self.automation_main_title = QtWidgets.QLineEdit(config.automation.main_window_title_contains)
            self.automation_ticket_title = QtWidgets.QLineEdit(config.automation.ticket_window_title_contains)
            self.automation_timeout = QtWidgets.QSpinBox()
            self.automation_timeout.setRange(2, 30)
            self.automation_timeout.setValue(config.automation.timeout_seconds)
            self.automation_click_x = QtWidgets.QDoubleSpinBox()
            self.automation_click_x.setRange(0.05, 0.95)
            self.automation_click_x.setSingleStep(0.01)
            self.automation_click_x.setDecimals(2)
            self.automation_click_x.setValue(config.automation.ticket_row_click_x)
            automation_note = QtWidgets.QLabel(
                "Test akışı yalnız GİRİŞ görselini okur, Plaka Değiştirme alanını doldurur "
                "ve Kaydet'e basmadan durur. ParkMatik bulunamazsa pencere başlığındaki sabit "
                "bir kelimeyi yazın."
            )
            automation_note.setWordWrap(True)
            layout.addRow("PTS otomasyonu", self.automation_enabled)
            layout.addRow("PTS pencere başlığı", self.automation_main_title)
            layout.addRow("Bilet Sorgulama başlığı", self.automation_ticket_title)
            layout.addRow("Satır sağ-tık yatay oranı", self.automation_click_x)
            layout.addRow("Zaman aşımı (sn)", self.automation_timeout)
            layout.addRow(automation_note)
        layout.addRow(note)
        layout.addRow(buttons)

    def _save(self) -> None:
        raw_hotkey = self.hotkey.keySequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        try:
            self.config.hotkey = normalize_hotkey(raw_hotkey)
            self.config.validate()
        except ValueError as error:
            QtWidgets.QMessageBox.warning(self, "Geçersiz OCR kısayolu", str(error))
            return
        self.config.debug.enabled = self.debug.isChecked()
        if self.automation_test:
            self.config.automation.enabled = self.automation_enabled.isChecked()
            self.config.automation.main_window_title_contains = self.automation_main_title.text().strip()
            self.config.automation.ticket_window_title_contains = self.automation_ticket_title.text().strip()
            self.config.automation.ticket_row_click_x = self.automation_click_x.value()
            self.config.automation.timeout_seconds = self.automation_timeout.value()
            try:
                self.config.automation.validate()
            except ValueError as error:
                QtWidgets.QMessageBox.warning(self, "Geçersiz otomasyon ayarı", str(error))
                return
        self.saved.emit(self.config)
        self.accept()
