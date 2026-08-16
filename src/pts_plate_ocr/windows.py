from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


if hasattr(ctypes, "WinDLL"):
    USER32 = ctypes.WinDLL("user32", use_last_error=True)
    KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # pragma: no cover - keeps imports inspectable on non-Windows CI.
    USER32 = None
    KERNEL32 = None


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process_id: int
    client_left: int
    client_top: int
    client_width: int
    client_height: int


def enable_dpi_awareness() -> None:
    if USER32 is None:
        return
    try:
        # Per-monitor-v2 makes screenshot pixels match Qt/mouse coordinates on scaled displays.
        USER32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            USER32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _window_title(hwnd: int) -> str:
    length = USER32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def window_info(hwnd: int) -> WindowInfo | None:
    if USER32 is None or not hwnd or not USER32.IsWindow(hwnd):
        return None
    if not USER32.IsWindowVisible(hwnd) or USER32.IsIconic(hwnd):
        return None
    rect = RECT()
    if not USER32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    top_left = POINT(rect.left, rect.top)
    bottom_right = POINT(rect.right, rect.bottom)
    if not USER32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        return None
    if not USER32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        return None
    process_id = wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    width, height = bottom_right.x - top_left.x, bottom_right.y - top_left.y
    if width <= 0 or height <= 0:
        return None
    return WindowInfo(
        hwnd=int(hwnd),
        title=_window_title(hwnd),
        process_id=int(process_id.value),
        client_left=top_left.x,
        client_top=top_left.y,
        client_width=width,
        client_height=height,
    )


def foreground_window_info() -> WindowInfo | None:
    return window_info(int(USER32.GetForegroundWindow())) if USER32 is not None else None


def find_window(title_contains: str) -> WindowInfo | None:
    if USER32 is None or not title_contains:
        return None
    target = title_contains.casefold()
    matches: list[WindowInfo] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _: int) -> bool:
        info = window_info(int(hwnd))
        if info and target in info.title.casefold():
            matches.append(info)
        return True

    USER32.EnumWindows(callback, 0)
    return matches[0] if matches else None

