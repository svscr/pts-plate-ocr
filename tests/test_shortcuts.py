import ctypes
from ctypes import wintypes

import pytest

from pts_plate_ocr.hotkey import HOTKEY_ID, WM_HOTKEY, HotkeyListener
from pts_plate_ocr.shortcuts import MOD_ALT, MOD_CONTROL, parse_hotkey
from pts_plate_ocr.windows import USER32


def test_ctrl_alt_letter_is_normalized_for_register_hotkey() -> None:
    shortcut = parse_hotkey("control+alt+p")
    assert shortcut.display == "Ctrl+Alt+P"
    assert shortcut.modifiers == MOD_CONTROL | MOD_ALT
    assert shortcut.virtual_key == ord("P")


def test_legacy_function_key_remains_supported() -> None:
    shortcut = parse_hotkey("f7")
    assert shortcut.display == "F7"
    assert shortcut.virtual_key == 0x76


def test_unmodified_letter_is_rejected() -> None:
    with pytest.raises(ValueError, match="Ctrl"):
        parse_hotkey("P")


@pytest.mark.skipif(USER32 is None, reason="Windows HWND test")
def test_hotkey_host_receives_wm_hotkey(qapp) -> None:
    listener = HotkeyListener()
    triggered: list[bool] = []
    listener.activated.connect(lambda: triggered.append(True))

    USER32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    USER32.SendMessageW.restype = ctypes.c_ssize_t
    USER32.SendMessageW(listener.window_handle, WM_HOTKEY, HOTKEY_ID, 0)

    assert triggered == [True]
