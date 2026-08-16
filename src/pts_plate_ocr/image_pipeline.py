from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageVariant:
    name: str
    image: np.ndarray


def upscale(image: np.ndarray, minimum_height: int = 96) -> np.ndarray:
    if image.size == 0:
        raise ValueError("Cannot upscale an empty image")
    scale = max(1.0, minimum_height / image.shape[0])
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def _clahe_gray(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)


def unsharp(image: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(image, (0, 0), 1.3)
    return cv2.addWeighted(image, 1.55, blurred, -0.55, 0)


def glare_ratio(image: np.ndarray) -> float:
    if image.ndim == 2:
        return float(np.mean(image > 245))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 245)
    return float(np.mean(mask))


def reduce_glare(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = np.uint8((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 245)) * 255
    mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8), iterations=1)
    return cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)


def preprocessing_variants(crop: np.ndarray) -> list[ImageVariant]:
    """Small, deliberately bounded ensemble for sub-100px plate crops."""
    base = upscale(crop)
    clahe = _clahe_gray(base)
    sharp = unsharp(clahe)
    threshold = cv2.adaptiveThreshold(
        clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        6,
    )
    variants = [
        ImageVariant("original_upscaled", base),
        ImageVariant("gray_clahe", cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)),
        ImageVariant("clahe_unsharp", cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)),
        ImageVariant("adaptive_threshold", cv2.cvtColor(threshold, cv2.COLOR_GRAY2BGR)),
    ]
    if glare_ratio(base) >= 0.03:
        variants.append(ImageVariant("glare_reduced", reduce_glare(base)))
    return variants


def crop_quad(image: np.ndarray, points: np.ndarray, padding: int = 6) -> np.ndarray:
    """Rectify a detected quadrilateral, falling back to a safe axis-aligned crop."""
    points = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(points) < 4:
        x, y, width, height = cv2.boundingRect(points)
        return padded_crop(image, x, y, width, height, padding)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    ordered = np.array(
        [points[np.argmin(sums)], points[np.argmin(diffs)], points[np.argmax(sums)], points[np.argmax(diffs)]],
        dtype=np.float32,
    )
    top = np.linalg.norm(ordered[1] - ordered[0])
    bottom = np.linalg.norm(ordered[2] - ordered[3])
    left = np.linalg.norm(ordered[3] - ordered[0])
    right = np.linalg.norm(ordered[2] - ordered[1])
    width, height = max(1, round(max(top, bottom))), max(1, round(max(left, right)))
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(ordered, target)
    crop = cv2.warpPerspective(image, transform, (width, height))
    return cv2.copyMakeBorder(crop, padding, padding, padding, padding, cv2.BORDER_REPLICATE)


def padded_crop(image: np.ndarray, x: int, y: int, width: int, height: int, padding: int = 6) -> np.ndarray:
    left, top = max(0, x - padding), max(0, y - padding)
    right, bottom = min(image.shape[1], x + width + padding), min(image.shape[0], y + height + padding)
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        raise ValueError("Detected crop is outside the source image")
    return crop

