"""User-confirmed UI automation for the separate ParkMatik test build.

This module deliberately works only through the visible Windows user
interface.  It never opens PTS files or databases and contains no code that
clicks the ``Kaydet`` button.  Its terminal state is a verified (when the
control is exposed) plate value in the *Plaka Değiştirme* text field; the user
must make the persistence decision by clicking ``Kaydet`` themselves.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum

import cv2
import mss
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .config import AppConfig, normalized_to_pixels
from .models import PixelRect, RecognitionResult, ResultStatus
from .plate import clean_ocr_text, is_date_like_plate
from .windows import POINT, RECT, USER32, WindowInfo, find_window, window_info

LOGGER = logging.getLogger(__name__)

WM_CLOSE = 0x0010
MN_GETHMENU = 0x01E1
MF_BYPOSITION = 0x0400
MIIM_STRING = 0x00000040
VK_CONTROL = 0x11
VK_A = 0x41
VK_V = 0x56

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", _INPUT_UNION)]


class _MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("fMask", wintypes.UINT),
        ("fType", wintypes.UINT),
        ("fState", wintypes.UINT),
        ("wID", wintypes.UINT),
        ("hSubMenu", wintypes.HANDLE),
        ("hbmpChecked", wintypes.HANDLE),
        ("hbmpUnchecked", wintypes.HANDLE),
        ("dwItemData", ctypes.c_size_t),
        ("dwTypeData", wintypes.LPWSTR),
        ("cch", wintypes.UINT),
        ("hbmpItem", wintypes.HANDLE),
    ]

if USER32 is not None:
    USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    USER32.SendInput.restype = wintypes.UINT
    USER32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    USER32.SetCursorPos.restype = wintypes.BOOL
    USER32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    USER32.PostMessageW.restype = wintypes.BOOL
    USER32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    USER32.SendMessageW.restype = ctypes.c_ssize_t
    USER32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    USER32.SetForegroundWindow.restype = wintypes.BOOL
    USER32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    USER32.ShowWindow.restype = wintypes.BOOL
    USER32.EnumChildWindows.argtypes = (wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM)
    USER32.EnumChildWindows.restype = wintypes.BOOL
    USER32.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
    USER32.EnumWindows.restype = wintypes.BOOL
    USER32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    USER32.GetClassNameW.restype = ctypes.c_int
    USER32.WindowFromPoint.argtypes = (POINT,)
    USER32.WindowFromPoint.restype = wintypes.HWND
    USER32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    USER32.GetWindowTextLengthW.restype = ctypes.c_int
    USER32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    USER32.GetWindowTextW.restype = ctypes.c_int
    USER32.SetFocus.argtypes = (wintypes.HWND,)
    USER32.SetFocus.restype = wintypes.HWND
    USER32.IsWindowEnabled.argtypes = (wintypes.HWND,)
    USER32.IsWindowEnabled.restype = wintypes.BOOL
    USER32.GetMenuItemCount.argtypes = (wintypes.HANDLE,)
    USER32.GetMenuItemCount.restype = ctypes.c_int
    USER32.GetMenuStringW.argtypes = (
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.UINT,
    )
    USER32.GetMenuStringW.restype = ctypes.c_int
    USER32.GetMenuItemInfoW.argtypes = (
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.BOOL,
        ctypes.POINTER(_MENUITEMINFOW),
    )
    USER32.GetMenuItemInfoW.restype = wintypes.BOOL
    USER32.GetMenuItemRect.argtypes = (
        wintypes.HWND,
        wintypes.HANDLE,
        wintypes.UINT,
        ctypes.POINTER(RECT),
    )
    USER32.GetMenuItemRect.restype = wintypes.BOOL


class AutomationState(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    WAITING_FOR_IMAGES = "waiting_for_images"
    READING_ENTRANCE = "reading_entrance"
    WAITING_FOR_IMAGE_CLOSE = "waiting_for_image_close"
    WAITING_FOR_EDITOR = "waiting_for_editor"
    FILLING_EDITOR = "filling_editor"


@dataclass(frozen=True)
class SelectedRow:
    center_y: int
    grid_rect: PixelRect


def _annotate_grid_preview(image: np.ndarray, selected: SelectedRow, click_x: int) -> np.ndarray:
    """Return an in-memory test preview of the explicit selected-row click point."""

    preview = image.copy()
    point = (click_x - selected.grid_rect.left, selected.center_y - selected.grid_rect.top)
    cv2.drawMarker(preview, point, (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
    cv2.putText(
        preview,
        "Sag tik noktasi",
        (max(4, point[0] + 10), max(18, point[1] - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 0, 255),
        1,
        cv2.LINE_AA,
    )
    return preview


def _capture(rect: PixelRect) -> np.ndarray:
    rect.validate()
    with mss.mss() as session:
        image = np.asarray(
            session.grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
        )
    return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)


def _looks_like_loaded_photo(image: np.ndarray) -> bool:
    """Conservatively distinguish a painted camera photo from blank PTS UI."""

    if image.ndim != 3 or image.shape[0] < 64 or image.shape[1] < 96 or image.shape[2] != 3:
        return False
    near_white_ratio = float(np.mean(np.all(image >= 235, axis=2)))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    contrast = float(np.std(gray))
    edge_ratio = float(np.mean(cv2.Canny(gray, 50, 150) > 0))
    return near_white_ratio < 0.65 and contrast >= 18.0 and edge_ratio >= 0.01


def _frames_are_stable(previous: np.ndarray, current: np.ndarray) -> bool:
    if previous.shape != current.shape or previous.size == 0:
        return False
    return float(np.mean(cv2.absdiff(previous, current))) <= 3.5


def _client_rect(window: WindowInfo) -> PixelRect:
    return PixelRect(window.client_left, window.client_top, window.client_width, window.client_height)


def _matches_title(window: WindowInfo | None, title_contains: str) -> bool:
    return bool(window and title_contains.casefold() in window.title.casefold())


def detect_selected_row(image: np.ndarray, grid_rect: PixelRect) -> SelectedRow | None:
    """Find ParkMatik's blue selected-row stripe without reading ticket data.

    The check is intentionally conservative: unless a broad blue stripe is
    visible, automation stops before a right-click can target an ambiguous row.
    """

    if image.ndim != 3 or image.shape[0] < 4 or image.shape[1] < 20:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([95, 80, 50]), np.array([135, 255, 255]))
    coverage = np.count_nonzero(blue, axis=1)
    threshold = max(16, int(image.shape[1] * 0.12))
    candidates = np.flatnonzero(coverage >= threshold)
    if candidates.size:
        groups: list[tuple[int, int, int]] = []
        start = previous = int(candidates[0])
        for row in candidates[1:]:
            current = int(row)
            if current > previous + 1:
                total = int(coverage[start : previous + 1].sum())
                groups.append((start, previous, total))
                start = current
            previous = current
        groups.append((start, previous, int(coverage[start : previous + 1].sum())))

        plausible = [group for group in groups if 3 <= group[1] - group[0] + 1 <= 48]
        if plausible:
            start, end, _ = max(plausible, key=lambda group: group[2])
            return SelectedRow(center_y=grid_rect.top + (start + end) // 2, grid_rect=grid_rect)

    # When ParkMatik loses active-row colouring (for example while a child
    # form is opening), the first grid column keeps the small black row-arrow
    # shown in the supplied screenshots.  It is a second explicit selection
    # signal, not a guess based on row position.
    selector_width = min(24, max(20, round(image.shape[1] * 0.018)))
    selector = image[:, :selector_width]
    dark = np.uint8(np.all(selector < 90, axis=2))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    candidates_by_shape: list[tuple[float, int, int]] = []
    for label in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[label])
        if x <= 0 or x > 12 or x + width >= selector_width:
            continue
        if not (4 <= width <= 14 and 6 <= height <= 22 and 8 <= area <= 100):
            continue
        component = labels[y : y + height, x : x + width] == label
        row_widths = np.count_nonzero(component, axis=1)
        peak = int(np.argmax(row_widths))
        peak_width = int(row_widths[peak])
        left_edge_coverage = float(np.count_nonzero(component[:, 0])) / height
        # ParkMatik's inactive-row marker is a filled right-facing triangle:
        # a mostly solid vertical left edge, a wide middle and narrow tips.
        if left_edge_coverage < 0.60:
            continue
        if not height * 0.20 <= peak <= height * 0.80:
            continue
        if peak_width < max(4, round(width * 0.70)):
            continue
        if row_widths[0] > peak_width * 0.60 or row_widths[-1] > peak_width * 0.60:
            continue
        score = area + left_edge_coverage * 20 + peak_width
        candidates_by_shape.append((score, y, height))
    if not candidates_by_shape:
        return None
    _, y, height = max(candidates_by_shape, key=lambda item: item[0])
    return SelectedRow(center_y=grid_rect.top + y + height // 2, grid_rect=grid_rect)


def _find_edit_control(dialog_handle: int) -> int | None:
    if USER32 is None:
        return None
    children: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(child: int, _: int) -> bool:
        class_name = ctypes.create_unicode_buffer(128)
        USER32.GetClassNameW(child, class_name, len(class_name))
        is_edit = "edit" in class_name.value.casefold()
        if is_edit and USER32.IsWindowVisible(child) and USER32.IsWindowEnabled(child):
            children.append(int(child))
        return True

    USER32.EnumChildWindows(dialog_handle, callback, 0)
    return children[0] if children else None


def _window_text(handle: int) -> str:
    if USER32 is None:
        return ""
    length = max(32, int(USER32.GetWindowTextLengthW(handle)) + 1)
    buffer = ctypes.create_unicode_buffer(length)
    USER32.GetWindowTextW(handle, buffer, len(buffer))
    return buffer.value


def _send_inputs(inputs: list[_INPUT]) -> bool:
    if USER32 is None or not inputs:
        return False
    batch_type = _INPUT * len(inputs)
    batch = batch_type(*inputs)
    sent = USER32.SendInput(len(batch), batch, ctypes.sizeof(_INPUT))
    return int(sent) == len(inputs)


def _mouse_input(flags: int) -> _INPUT:
    return _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(dwFlags=flags))


def _key_input(virtual_key: int, key_up: bool = False) -> _INPUT:
    return _INPUT(
        type=INPUT_KEYBOARD,
        ki=_KEYBDINPUT(wVk=virtual_key, dwFlags=KEYEVENTF_KEYUP if key_up else 0),
    )


def _click(x: int, y: int, *, right: bool = False) -> bool:
    if USER32 is None or not USER32.SetCursorPos(x, y):
        return False
    if right:
        return _send_inputs([_mouse_input(MOUSEEVENTF_RIGHTDOWN), _mouse_input(MOUSEEVENTF_RIGHTUP)])
    return _send_inputs([_mouse_input(MOUSEEVENTF_LEFTDOWN), _mouse_input(MOUSEEVENTF_LEFTUP)])


def _paste_from_clipboard() -> bool:
    return _send_inputs(
        [
            _key_input(VK_CONTROL),
            _key_input(VK_A),
            _key_input(VK_A, key_up=True),
            _key_input(VK_CONTROL, key_up=True),
            _key_input(VK_CONTROL),
            _key_input(VK_V),
            _key_input(VK_V, key_up=True),
            _key_input(VK_CONTROL, key_up=True),
        ]
    )


def _focus_window(handle: int) -> bool:
    if USER32 is None:
        return False
    USER32.ShowWindow(handle, SW_RESTORE)
    return bool(USER32.SetForegroundWindow(handle))


def _normalize_menu_text(value: str) -> str:
    without_markers = value.replace("&", "").replace("…", "").replace("...", "")
    return " ".join(without_markers.split()).casefold()


def _find_popup_menu_windows() -> list[int]:
    """Return every visible native popup menu without guessing which app owns it."""

    if USER32 is None:
        return None
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(handle: int, _: int) -> bool:
        class_name = ctypes.create_unicode_buffer(32)
        USER32.GetClassNameW(handle, class_name, len(class_name))
        if class_name.value == "#32768" and USER32.IsWindowVisible(handle):
            matches.append(int(handle))
        return True

    USER32.EnumWindows(callback, 0)
    return matches


def _menu_item_text(menu: int, position: int) -> str:
    """Read a native menu label, including menus where GetMenuStringW is empty."""

    if USER32 is None:
        return ""
    buffer = ctypes.create_unicode_buffer(512)
    copied = USER32.GetMenuStringW(menu, position, buffer, len(buffer), MF_BYPOSITION)
    if copied > 0:
        return buffer.value

    info = _MENUITEMINFOW(
        cbSize=ctypes.sizeof(_MENUITEMINFOW),
        fMask=MIIM_STRING,
        dwTypeData=ctypes.cast(buffer, wintypes.LPWSTR),
        cch=len(buffer) - 1,
    )
    if USER32.GetMenuItemInfoW(menu, position, True, ctypes.byref(info)):
        return buffer.value
    return ""


def _cursor_window_description(anchor: tuple[int, int]) -> str:
    """Describe the control under the contextual-menu anchor for safe diagnostics."""

    if USER32 is None:
        return ""
    handle = int(USER32.WindowFromPoint(POINT(*anchor)))
    if not handle:
        return "imleç altında pencere yok"
    class_name = ctypes.create_unicode_buffer(128)
    USER32.GetClassNameW(handle, class_name, len(class_name))
    title = _window_text(handle).strip()
    if title:
        return f"imleç kontrolü: {class_name.value} ({title[:60]})"
    return f"imleç kontrolü: {class_name.value or 'başlıksız'}"


def _click_verified_menu_item(expected_text: str, *, anchor: tuple[int, int]) -> tuple[bool, str]:
    """Click a popup item only after Windows reports its exact displayed text.

    It deliberately has no keyboard-index fallback.  If ParkMatik changes the
    context menu implementation or wording, the test build stops rather than
    guessing which menu item might be selected.
    """

    if USER32 is None:
        return False, "Windows menü API'si kullanılamıyor"
    popups = _find_popup_menu_windows()
    if not popups:
        return False, "görünür açılır menü bulunamadı; " + _cursor_window_description(anchor)
    wanted = _normalize_menu_text(expected_text)
    observed: list[str] = []
    for popup in popups:
        menu = int(USER32.SendMessageW(popup, MN_GETHMENU, 0, 0))
        count = int(USER32.GetMenuItemCount(menu)) if menu else -1
        if count <= 0:
            continue
        for position in range(count):
            text = _menu_item_text(menu, position)
            if text:
                observed.append(text)
            if _normalize_menu_text(text) != wanted:
                continue
            rect = RECT()
            if not USER32.GetMenuItemRect(popup, menu, position, ctypes.byref(rect)):
                return False, "doğrulanan menü öğesinin ekran konumu alınamadı"
            if rect.left >= rect.right or rect.top >= rect.bottom:
                return False, "doğrulanan menü öğesinin ekran alanı geçersiz"
            return _click((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2), ""
    if observed:
        return False, "görünen menü öğeleri: " + ", ".join(observed[:6])
    return False, "menü öğesi metinleri okunamadı"


class PtsAutomationController(QtCore.QObject):
    """Small state machine ending before the user's explicit Save action."""

    ocr_requested = QtCore.Signal(object)
    preview_ready = QtCore.Signal(object)
    finished = QtCore.Signal(bool, str)
    message = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.state = AutomationState.IDLE
        self.config: AppConfig | None = None
        self.main_window: WindowInfo | None = None
        self.image_window: WindowInfo | None = None
        self.selected_row: SelectedRow | None = None
        self.plate = ""
        self._deadline = 0.0
        self._edit_handle: int | None = None
        self._pending_photo: np.ndarray | None = None

    @property
    def busy(self) -> bool:
        return self.state != AutomationState.IDLE

    def start(self, config: AppConfig) -> bool:
        if self.busy:
            self.message.emit("PTS otomasyonu zaten çalışıyor.")
            return False
        if USER32 is None:
            self.message.emit("PTS otomasyonu yalnız Windows'ta kullanılabilir.")
            return False
        if not config.automation.enabled:
            self.message.emit("PTS otomasyonu ayarlardan kapalı.")
            return False

        main = find_window(config.automation.ticket_window_title_contains)
        if main is None:
            self.message.emit(
                "Bilet Sorgulama penceresi bulunamadı. Pencere açık ve önde olmalı; başlık ayarını kontrol edin."
            )
            return False

        self.config = config
        self.main_window = main
        self.image_window = None
        self.selected_row = None
        self.plate = ""
        self._edit_handle = None
        self._pending_photo = None
        self.state = AutomationState.PREPARING
        if not _focus_window(main.hwnd):
            self._finish(False, "ParkMatik penceresi öne getirilemedi; işlem başlatılmadı.")
            return False
        QtCore.QTimer.singleShot(180, self._begin_on_main_window)
        return True

    def handle_ocr_result(self, result: RecognitionResult) -> None:
        if self.state != AutomationState.READING_ENTRANCE:
            return
        if result.status != ResultStatus.HIGH_CONFIDENCE or not result.plate:
            detail = result.message or "Giriş görselinde yüksek güvenli plaka bulunamadı."
            if result.status == ResultStatus.NO_READ and result.raw_readings:
                detail += " Ham OCR: " + " | ".join(result.raw_readings)
            self._finish(False, f"PTS'ye hiçbir şey yazılmadı. {detail}")
            return
        plate = clean_ocr_text(result.plate)
        if not plate:
            self._finish(False, "OCR sonucu geçerli bir plaka değil; PTS'ye hiçbir şey yazılmadı.")
            return
        if is_date_like_plate(plate):
            self._finish(
                False,
                "Tarih benzeri OCR sonucu reddedildi; PTS'ye hiçbir şey yazılmadı.",
            )
            return
        self.plate = plate
        QtWidgets.QApplication.clipboard().setText(plate)
        self.state = AutomationState.WAITING_FOR_IMAGE_CLOSE
        if self.image_window is None or not USER32.PostMessageW(self.image_window.hwnd, WM_CLOSE, 0, 0):
            self._finish(False, "Görsel penceresi güvenle kapatılamadı; PTS'ye hiçbir şey yazılmadı.")
            return
        self._deadline = time.monotonic() + self._timeout_seconds
        self._wait_for_image_close()

    def _begin_on_main_window(self) -> None:
        if self.config is None or self.main_window is None:
            self._finish(False, "Otomasyon başlangıç durumu kayboldu.")
            return
        current = window_info(self.main_window.hwnd)
        if not _matches_title(current, self.config.automation.ticket_window_title_contains):
            self._finish(False, "Bilet Sorgulama penceresi doğrulanamadı; işlem başlatılmadı.")
            return
        grid = normalized_to_pixels(self.config.automation.ticket_grid_roi, _client_rect(current))
        grid_image = _capture(grid)
        selected = detect_selected_row(grid_image, grid)
        if selected is None:
            self._finish(
                False,
                "Seçili bilet satırı bulunamadı. Bilet Sorgulama'da tek satırı seçip tekrar deneyin.",
            )
            return
        self.main_window = current
        self.selected_row = selected
        click_x = self.selected_row.grid_rect.left + round(
            self.selected_row.grid_rect.width * self.config.automation.ticket_row_click_x
        )
        self.preview_ready.emit(_annotate_grid_preview(grid_image, self.selected_row, click_x))
        self._open_context_menu(
            item_text="Araç Resimlerini Göster",
            next_title=self.config.automation.image_dialog_title_contains,
        )

    def _open_context_menu(self, *, item_text: str, next_title: str) -> None:
        if self.config is None or self.selected_row is None:
            self._finish(False, "Seçili satır doğrulaması kayboldu.")
            return
        x = self.selected_row.grid_rect.left + round(
            self.selected_row.grid_rect.width * self.config.automation.ticket_row_click_x
        )
        if not _click(x, self.selected_row.center_y, right=True):
            self._finish(False, "PTS satırına sağ tıklanamadı; işlem durduruldu.")
            return
        self._deadline = time.monotonic() + self._timeout_seconds

        def choose_item() -> None:
            clicked, detail = _click_verified_menu_item(item_text, anchor=(x, self.selected_row.center_y))
            if clicked:
                self._wait_for_named_window(next_title)
                return
            if time.monotonic() >= self._deadline:
                suffix = f" ({detail})" if detail else ""
                self._finish(
                    False,
                    f"PTS sağ-tık menüsünde '{item_text}' doğrulanamadı; seçim yapılmadı.{suffix}",
                )
                return
            QtCore.QTimer.singleShot(80, choose_item)

        QtCore.QTimer.singleShot(140, choose_item)

    def _wait_for_named_window(self, title: str) -> None:
        found = find_window(title)
        if found is not None:
            if self.config is None:
                self._finish(False, "Otomasyon ayarları kayboldu.")
                return
            if title.casefold() == self.config.automation.image_dialog_title_contains.casefold():
                self.image_window = found
                self.state = AutomationState.WAITING_FOR_IMAGES
                self._pending_photo = None
                self._deadline = time.monotonic() + self._timeout_seconds
                QtCore.QTimer.singleShot(200, self._wait_for_entrance_image_ready)
            else:
                self.state = AutomationState.FILLING_EDITOR
                self._fill_plate_field(found)
            return
        if time.monotonic() >= self._deadline:
            self._finish(False, f"Beklenen PTS penceresi açılmadı: {title}")
            return
        QtCore.QTimer.singleShot(100, lambda: self._wait_for_named_window(title))

    def _wait_for_entrance_image_ready(self) -> None:
        if self.config is None or self.image_window is None:
            self._finish(False, "Giriş fotoğrafı penceresi doğrulanamadı.")
            return
        current = window_info(self.image_window.hwnd)
        if not _matches_title(current, self.config.automation.image_dialog_title_contains):
            self._finish(False, "Giriş fotoğrafı penceresi doğrulanamadı.")
            return
        photo_rect = normalized_to_pixels(self.config.automation.entrance_photo_roi, _client_rect(current))
        photo = _capture(photo_rect)
        if not _looks_like_loaded_photo(photo):
            self._pending_photo = None
        elif self._pending_photo is not None and _frames_are_stable(self._pending_photo, photo):
            self._pending_photo = None
            self._capture_entrance_image(photo, current)
            return
        else:
            self._pending_photo = photo

        if time.monotonic() >= self._deadline:
            self._finish(
                False,
                "Giriş fotoğrafı yüklenmedi veya sabitlenmedi; PTS'ye hiçbir şey yazılmadı.",
            )
            return
        QtCore.QTimer.singleShot(180, self._wait_for_entrance_image_ready)

    def _capture_entrance_image(self, photo: np.ndarray, current: WindowInfo) -> None:
        if self.config is None:
            self._finish(False, "Giriş fotoğrafı ayarları kayboldu.")
            return
        search_rect = normalized_to_pixels(
            self.config.automation.entrance_plate_search_roi,
            PixelRect(0, 0, photo.shape[1], photo.shape[0]),
        )
        search_band = photo[search_rect.top : search_rect.bottom, search_rect.left : search_rect.right]
        if search_band.size == 0:
            self._finish(False, "Giriş fotoğrafı için plaka arama alanı geçersiz.")
            return
        self.image_window = current
        self.state = AutomationState.READING_ENTRANCE
        self.message.emit("Yalnız giriş görseli okunuyor…")
        self.ocr_requested.emit(search_band)

    def _wait_for_image_close(self) -> None:
        if self.image_window is None or window_info(self.image_window.hwnd) is None:
            if self.main_window is None or not _focus_window(self.main_window.hwnd):
                self._finish(False, "ParkMatik penceresi tekrar öne getirilemedi; PTS'ye hiçbir şey yazılmadı.")
                return
            QtCore.QTimer.singleShot(160, self._verify_row_and_open_editor)
            return
        if time.monotonic() >= self._deadline:
            self._finish(False, "Görsel penceresinin kapanması zaman aşımına uğradı.")
            return
        QtCore.QTimer.singleShot(100, self._wait_for_image_close)

    def _verify_row_and_open_editor(self) -> None:
        if self.config is None or self.main_window is None or self.selected_row is None:
            self._finish(False, "Seçili bilet bilgisi kayboldu; PTS'ye hiçbir şey yazılmadı.")
            return
        current = window_info(self.main_window.hwnd)
        if not _matches_title(current, self.config.automation.ticket_window_title_contains):
            self._finish(False, "Bilet Sorgulama penceresi doğrulanamadı; PTS'ye hiçbir şey yazılmadı.")
            return
        grid = normalized_to_pixels(self.config.automation.ticket_grid_roi, _client_rect(current))
        current_selected = detect_selected_row(_capture(grid), grid)
        if current_selected is None or abs(current_selected.center_y - self.selected_row.center_y) > 6:
            self._finish(
                False,
                "Aynı seçili bilet satırı doğrulanamadı; PTS'ye hiçbir şey yazılmadı.",
            )
            return
        self.main_window = current
        self.selected_row = current_selected
        self.state = AutomationState.WAITING_FOR_EDITOR
        self._open_context_menu(
            item_text="Plaka Değiştir",
            next_title=self.config.automation.plate_dialog_title_contains,
        )

    def _fill_plate_field(self, dialog: WindowInfo) -> None:
        if self.config is None or not self.plate:
            self._finish(False, "Plaka değeri kayboldu; PTS'ye hiçbir şey yazılmadı.")
            return
        if not _matches_title(dialog, self.config.automation.plate_dialog_title_contains):
            self._finish(False, "Plaka Değiştirme penceresi doğrulanamadı.")
            return
        if not _focus_window(dialog.hwnd):
            self._finish(False, "Plaka Değiştirme penceresi öne getirilemedi.")
            return
        self._edit_handle = _find_edit_control(dialog.hwnd)
        if self._edit_handle is not None:
            USER32.SetFocus(self._edit_handle)
        else:
            input_rect = normalized_to_pixels(self.config.automation.plate_input_roi, _client_rect(dialog))
            if not _click(input_rect.left + input_rect.width // 2, input_rect.top + input_rect.height // 2):
                self._finish(False, "Plaka metin alanına güvenle odaklanılamadı.")
                return
        QtWidgets.QApplication.clipboard().setText(self.plate)
        QtCore.QTimer.singleShot(80, self._paste_plate)

    def _paste_plate(self) -> None:
        if not _paste_from_clipboard():
            self._finish(False, "Plaka panodan alana yapıştırılamadı.")
            return
        QtCore.QTimer.singleShot(180, self._verify_paste)

    def _verify_paste(self) -> None:
        if self._edit_handle is not None:
            written = clean_ocr_text(_window_text(self._edit_handle))
            if written != self.plate:
                self._finish(
                    False,
                    "Plaka alanındaki değer doğrulanamadı. Kaydet'e basmayın; PTS'ye kayıt yapılmadı.",
                )
                return
        verification = "Alanı gözle kontrol edip " if self._edit_handle is None else ""
        self._finish(
            True,
            f"{self.plate} Plaka alanına yazıldı. {verification}Kaydet'e yalnız siz basın.",
        )

    @property
    def _timeout_seconds(self) -> int:
        return self.config.automation.timeout_seconds if self.config else 6

    def _finish(self, success: bool, text: str) -> None:
        LOGGER.info("PTS automation finished success=%s: %s", success, text)
        self._pending_photo = None
        self.state = AutomationState.IDLE
        self.finished.emit(success, text)


class AutomationPanel(QtWidgets.QDialog):
    """Explicit user launch point for the no-save automation test."""

    start_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PTS Otomasyonu — Test")
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(410)
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel("Seçili bileti giriş görselinden doldur")
        heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        note = QtWidgets.QLabel(
            "1. ParkMatik'te Bilet Sorgulama ekranına geçin ve tek, plakası boş bileti seçin.\n"
            "2. Aşağıdaki düğme yalnız GİRİŞ görselini okur.\n"
            "3. Uygulama Plaka Değiştirme alanını doldurur; Kaydet'e asla basmaz."
        )
        note.setWordWrap(True)
        self.start_button = QtWidgets.QPushButton("Seçili bileti oku ve Plaka alanını doldur")
        self.start_button.clicked.connect(self._start)
        self.status = QtWidgets.QLabel("Hazır. Kaydet işlemi her zaman sizdedir.")
        self.status.setWordWrap(True)
        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setVisible(False)
        close_button = QtWidgets.QPushButton("Kapat")
        close_button.clicked.connect(self.close)
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addSpacing(8)
        layout.addWidget(self.start_button)
        layout.addWidget(self.status)
        layout.addWidget(self.preview)
        layout.addWidget(close_button)

    def _start(self) -> None:
        self.preview.clear()
        self.preview.setVisible(False)
        self.status.setText("PTS otomasyonu hazırlanıyor…")
        self.hide()
        self.start_requested.emit()

    def set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_grid_preview(self, image: object) -> None:
        if not isinstance(image, np.ndarray) or image.size == 0:
            return
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width, _ = rgb.shape
        qimage = QtGui.QImage(rgb.data, width, height, width * 3, QtGui.QImage.Format.Format_RGB888).copy()
        pixmap = QtGui.QPixmap.fromImage(qimage)
        self.preview.setPixmap(
            pixmap.scaledToWidth(680, QtCore.Qt.TransformationMode.SmoothTransformation)
        )
        self.preview.setVisible(True)
        self.adjustSize()
