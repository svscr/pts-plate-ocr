"""Parsing and normalisation for supported global Windows shortcuts."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_HOTKEY = "Ctrl+Alt+P"

# RegisterHotKey modifier flags.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

_MODIFIER_ALIASES = {
    "ALT": ("Alt", MOD_ALT),
    "CTRL": ("Ctrl", MOD_CONTROL),
    "CONTROL": ("Ctrl", MOD_CONTROL),
    "SHIFT": ("Shift", MOD_SHIFT),
}
_MODIFIER_ORDER = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT))
_SPECIAL_KEYS = {"SPACE": ("Space", 0x20)}


@dataclass(frozen=True)
class HotkeySpec:
    """A validated shortcut ready for the Windows RegisterHotKey API."""

    display: str
    modifiers: int
    virtual_key: int


def _parse_key(token: str) -> tuple[str, int, bool]:
    if token in _SPECIAL_KEYS:
        display, virtual_key = _SPECIAL_KEYS[token]
        return display, virtual_key, False
    if len(token) == 1 and ("A" <= token <= "Z" or "0" <= token <= "9"):
        return token, ord(token), False
    if token.startswith("F") and token[1:].isdigit():
        number = int(token[1:])
        if 1 <= number <= 24:
            return f"F{number}", 0x6F + number, True
    raise ValueError(
        "Desteklenen tuşlar A-Z, 0-9, Space ve F1-F24'tür. "
        "Örnek: Ctrl+Alt+P"
    )


def parse_hotkey(value: str) -> HotkeySpec:
    """Validate a user shortcut and return its canonical Windows representation."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("Bir OCR kısayolu seçin; örneğin Ctrl+Alt+P.")
    tokens = [part.strip().upper() for part in value.split("+")]
    if any(not token for token in tokens):
        raise ValueError("Kısayolda boş bir tuş bölümü olamaz.")

    modifiers = 0
    key_token: str | None = None
    for token in tokens:
        modifier = _MODIFIER_ALIASES.get(token)
        if modifier is not None:
            _, modifier_bit = modifier
            if modifiers & modifier_bit:
                raise ValueError(f"{modifier[0]} birden fazla yazılmış.")
            modifiers |= modifier_bit
            continue
        if key_token is not None:
            raise ValueError("Kısayolda yalnız bir ana tuş kullanılabilir.")
        key_token = token

    if key_token is None:
        raise ValueError("Kısayola bir harf, rakam veya fonksiyon tuşu ekleyin.")
    key_display, virtual_key, is_function_key = _parse_key(key_token)
    if not modifiers and not is_function_key:
        raise ValueError("Harf ve rakam kısayollarında Ctrl, Alt veya Shift kullanın; örneğin Ctrl+Alt+P.")

    display_parts = [name for name, bit in _MODIFIER_ORDER if modifiers & bit]
    display_parts.append(key_display)
    return HotkeySpec(display="+".join(display_parts), modifiers=modifiers, virtual_key=virtual_key)


def normalize_hotkey(value: str) -> str:
    """Return a stable config/UI spelling after validating a shortcut."""

    return parse_hotkey(value).display
