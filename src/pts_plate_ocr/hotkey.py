from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6 import QtCore, QtWidgets

from .shortcuts import MOD_NOREPEAT, parse_hotkey
from .windows import USER32

WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5054
_WINDOWS_MESSAGE_TYPES = {b"windows_generic_MSG", b"windows_dispatcher_MSG"}

if USER32 is not None:
    USER32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
    USER32.RegisterHotKey.restype = wintypes.BOOL
    USER32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    USER32.UnregisterHotKey.restype = wintypes.BOOL


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("lPrivate", wintypes.DWORD),
    ]


class _HotkeyHost(QtWidgets.QWidget):
    """An invisible HWND that receives the WM_HOTKEY sent by RegisterHotKey."""

    activated = QtCore.Signal()

    def __init__(self, hotkey_id: int) -> None:
        super().__init__()
        self.hotkey_id = hotkey_id
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setWindowFlags(QtCore.Qt.WindowType.Tool)
        # Force HWND creation before RegisterHotKey is called.
        self.winId()

    def nativeEvent(self, event_type: bytes, message: int) -> tuple[bool, int]:  # noqa: N802
        if bytes(event_type) in _WINDOWS_MESSAGE_TYPES:
            event = MSG.from_address(int(message))
            if event.message == WM_HOTKEY and int(event.wParam) == self.hotkey_id:
                self.activated.emit()
                return True, 0
        return super().nativeEvent(event_type, message)


class HotkeyListener(QtCore.QObject):
    activated = QtCore.Signal()

    def __init__(self, hotkey_id: int = HOTKEY_ID) -> None:
        super().__init__()
        self.hotkey_id = hotkey_id
        self._registered = False
        self._hotkey = ""
        self._host: _HotkeyHost | None = None

    def _ensure_host(self) -> _HotkeyHost:
        if self._host is None:
            self._host = _HotkeyHost(self.hotkey_id)
            self._host.activated.connect(self.activated.emit)
        return self._host

    @property
    def window_handle(self) -> int:
        return int(self._ensure_host().winId())

    def register(self, hotkey: str) -> None:
        if USER32 is None:
            raise RuntimeError("Global hotkey yalnızca Windows'ta desteklenir.")
        spec = parse_hotkey(hotkey)
        self.unregister()
        if not USER32.RegisterHotKey(
            self.window_handle, self.hotkey_id, spec.modifiers | MOD_NOREPEAT, spec.virtual_key
        ):
            error = ctypes.get_last_error()
            raise RuntimeError(
                f"{spec.display} başka bir uygulama tarafından kullanılıyor veya Windows tarafından ayrılmış "
                f"(Windows hata kodu {error})."
            )
        self._hotkey = spec.display
        self._registered = True

    def unregister(self) -> None:
        if self._registered and USER32 is not None:
            USER32.UnregisterHotKey(self.window_handle, self.hotkey_id)
        self._registered = False
