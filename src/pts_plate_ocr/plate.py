from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from datetime import date


_ALNUM = re.compile(r"[^A-Z0-9]")
_DIGIT_TO_LETTER = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "6": "G"}
_LETTER_TO_DIGIT = {value: key for key, value in _DIGIT_TO_LETTER.items()}


@dataclass(frozen=True)
class ParsedPlate:
    canonical: str
    compact: str
    correction_count: int
    source: str


def clean_ocr_text(text: str) -> str:
    normalized = text.upper().replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
    return _ALNUM.sub("", normalized)


def is_date_like_plate(text: str) -> bool:
    """Reject dates that OCR can reshape into a syntactically valid plate.

    A displayed date such as ``15.08.2026`` may be read as ``15O82026``.
    That string otherwise looks like province 15, letter O and five digits.
    Keep this rule deliberately narrow so real Turkish plates are not rejected.
    """

    compact = clean_ocr_text(text)
    if len(compact) != 8 or not compact[:2].isdigit() or not compact[3:].isdigit():
        return False
    substituted = _LETTER_TO_DIGIT.get(compact[2])
    if substituted is None:
        return False
    digits = compact[:2] + substituted + compact[3:]
    day, month, year = int(digits[:2]), int(digits[2:4]), int(digits[4:])
    if not 2000 <= year <= 2099:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _is_province(value: str) -> bool:
    return len(value) == 2 and value.isdigit() and 1 <= int(value) <= 81


def _segment(compact: str) -> list[str]:
    """Return all structurally valid segments without making substitutions."""
    if len(compact) < 5:
        return []
    province = compact[:2]
    if not _is_province(province):
        return []
    plates: list[str] = []
    for letter_length in range(1, 4):
        suffix_start = 2 + letter_length
        suffix_length = len(compact) - suffix_start
        if not 2 <= suffix_length <= 5:
            continue
        letters, digits = compact[2:suffix_start], compact[suffix_start:]
        if letters.isalpha() and letters.isascii() and digits.isdigit():
            # PTS accepts the compact representation directly; it is also safer
            # for clipboard use because no intermediate whitespace is pasted.
            plates.append(f"{province}{letters}{digits}")
    return plates


def _position_aware_variants(compact: str, max_corrections: int) -> list[tuple[str, int]]:
    """Generate limited OCR-confusion alternatives; never apply global replacement."""
    variants: dict[str, int] = {compact: 0}
    # Province positions must be digits. Later positions are tried as every legal segmentation.
    positions: list[tuple[int, str]] = []
    for index, char in enumerate(compact):
        if index < 2 and char in _LETTER_TO_DIGIT:
            positions.append((index, _LETTER_TO_DIGIT[char]))
        elif index >= 2:
            if char in _DIGIT_TO_LETTER:
                positions.append((index, _DIGIT_TO_LETTER[char]))
            if char in _LETTER_TO_DIGIT:
                positions.append((index, _LETTER_TO_DIGIT[char]))

    for count in range(1, max_corrections + 1):
        for selection in itertools.combinations(positions, count):
            indexes = [index for index, _ in selection]
            if len(set(indexes)) != len(indexes):
                continue
            chars = list(compact)
            for index, substitute in selection:
                chars[index] = substitute
            variants.setdefault("".join(chars), count)
    return list(variants.items())


def parse_candidates(text: str, max_corrections: int = 2) -> list[ParsedPlate]:
    """Parse standard single-line Turkish civilian plate candidates from OCR text."""
    compact = clean_ocr_text(text)
    if not compact:
        return []
    # Stop before confusion substitutions can reshape a date into another
    # syntactically valid plate candidate (for example 15O82026 -> 15OB2026).
    if is_date_like_plate(compact):
        return []
    results: dict[str, ParsedPlate] = {}
    for variant, correction_count in _position_aware_variants(compact, max_corrections):
        for canonical in _segment(variant):
            if is_date_like_plate(canonical):
                continue
            current = ParsedPlate(
                canonical=canonical,
                compact=variant,
                correction_count=correction_count,
                source=compact,
            )
            existing = results.get(canonical)
            if existing is None or current.correction_count < existing.correction_count:
                results[canonical] = current
    # One-letter/five-digit plates are legal, but are a less useful tie-breaker when
    # the exact same OCR stream also supports a 2–3 letter standard plate.
    def sort_key(item: ParsedPlate) -> tuple[int, int, str]:
        letter_count = len(item.compact[2:].rstrip("0123456789"))
        letter_preference = {3: 0, 2: 1, 1: 2}[letter_count]
        return item.correction_count, letter_preference, item.canonical

    return sorted(results.values(), key=sort_key)


def parse_best(text: str, max_corrections: int = 2) -> ParsedPlate | None:
    candidates = parse_candidates(text, max_corrections=max_corrections)
    return candidates[0] if candidates else None
