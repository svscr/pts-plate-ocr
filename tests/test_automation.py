import cv2
import numpy as np

from pts_plate_ocr.automation import (
    _frames_are_stable,
    _looks_like_loaded_photo,
    _normalize_menu_text,
    detect_selected_row,
)
from pts_plate_ocr.models import PixelRect


def test_selected_parkmatik_row_is_detected_from_blue_highlight() -> None:
    image = np.zeros((80, 240, 3), dtype=np.uint8)
    # BGR equivalent of the blue row highlight in the supplied ParkMatik UI.
    image[28:43, :, :] = (192, 112, 0)
    grid = PixelRect(40, 120, 240, 80)

    selected = detect_selected_row(image, grid)

    assert selected is not None
    assert selected.center_y == 155


def test_no_blue_row_means_no_automation_target() -> None:
    image = np.full((80, 240, 3), 230, dtype=np.uint8)
    assert detect_selected_row(image, PixelRect(0, 0, 240, 80)) is None


def test_inactive_row_arrow_is_detected_when_blue_highlight_is_absent() -> None:
    image = np.full((80, 240, 3), 230, dtype=np.uint8)
    arrow = np.array([[7, 28], [7, 42], [16, 35]], dtype=np.int32)
    cv2.fillConvexPoly(image, arrow, (0, 0, 0))

    selected = detect_selected_row(image, PixelRect(40, 120, 240, 80))

    assert selected is not None
    assert selected.center_y == 155


def test_vertical_ticket_digit_is_not_mistaken_for_row_arrow() -> None:
    image = np.full((80, 240, 3), 230, dtype=np.uint8)
    image[28:43, 7:10] = (0, 0, 0)

    assert detect_selected_row(image, PixelRect(40, 120, 240, 80)) is None


def test_menu_text_matching_ignores_accelerators_and_ellipsis() -> None:
    assert _normalize_menu_text("&Plaka Değiştir…") == "plaka değiştir"
    assert _normalize_menu_text("Araç\t Resimlerini   Göster") == "araç resimlerini göster"


def test_blank_pts_area_is_not_accepted_as_loaded_photo() -> None:
    blank = np.full((180, 320, 3), 245, dtype=np.uint8)
    cv2.putText(blank, "15.08.2026", (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)

    assert not _looks_like_loaded_photo(blank)


def test_textured_camera_frame_is_accepted_and_stability_is_checked() -> None:
    rng = np.random.default_rng(379)
    frame = rng.integers(20, 220, size=(180, 320, 3), dtype=np.uint8)

    assert _looks_like_loaded_photo(frame)
    assert _frames_are_stable(frame, frame.copy())
    assert not _frames_are_stable(frame, np.full_like(frame, 255))
