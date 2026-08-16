from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import mss
import numpy as np

from .config import AppConfig, normalized_to_pixels
from .models import PixelRect
from .windows import find_window

LOGGER = logging.getLogger(__name__)


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureFrame:
    photo: np.ndarray
    search_band: np.ndarray
    photo_rect: PixelRect


def _grab(rect: PixelRect) -> np.ndarray:
    rect.validate()
    with mss.mss() as session:
        image = np.asarray(
            session.grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
        )
    return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)


def _primary_monitor_rect() -> PixelRect:
    with mss.mss() as session:
        monitor = session.monitors[1]
    return PixelRect(monitor["left"], monitor["top"], monitor["width"], monitor["height"])


def resolve_photo_rect(config: AppConfig) -> PixelRect:
    if config.window_matcher and config.photo_roi_relative_to_window:
        window = find_window(config.window_matcher.title_contains)
        if window is None:
            raise CaptureError("Kalibre edilmiş PTS penceresi görünür değil. Yeniden kalibrasyon gerekebilir.")
        return normalized_to_pixels(
            config.photo_roi_relative_to_window,
            PixelRect(window.client_left, window.client_top, window.client_width, window.client_height),
        )
    return normalized_to_pixels(config.desktop_photo_roi, _primary_monitor_rect())


def capture_frame(config: AppConfig) -> CaptureFrame:
    photo_rect = resolve_photo_rect(config)
    photo = _grab(photo_rect)
    search_rect = normalized_to_pixels(
        config.plate_search_roi,
        PixelRect(0, 0, photo.shape[1], photo.shape[0]),
    )
    search_band = photo[search_rect.top : search_rect.bottom, search_rect.left : search_rect.right]
    if search_band.size == 0:
        raise CaptureError("Plaka arama bölgesi geçersiz.")
    return CaptureFrame(photo=photo, search_band=search_band, photo_rect=photo_rect)

