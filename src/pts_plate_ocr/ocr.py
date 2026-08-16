from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np
from rapidocr import RapidOCR

from .image_pipeline import crop_quad, preprocessing_variants
from .models import PlateCandidate, RecognitionResult, ResultStatus
from .plate import parse_candidates

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextDetection:
    text: str
    score: float
    box: np.ndarray | None = None

    @property
    def geometry_score(self) -> float:
        if self.box is None:
            return 0.45
        x, y, width, height = cv2.boundingRect(np.asarray(self.box, dtype=np.float32))
        if height <= 0:
            return 0.45
        ratio = width / height
        return 1.0 if 1.5 <= ratio <= 9.5 else 0.55


@dataclass(frozen=True)
class Observation:
    plate: str
    raw_text: str
    ocr_score: float
    variant: str
    correction_count: int
    geometry_score: float


class LocalPlateOcr:
    """RapidOCR-backed, fully local OCR pipeline. The model is loaded lazily."""

    def __init__(self) -> None:
        self._engine: RapidOCR | None = None

    @property
    def engine(self) -> RapidOCR:
        if self._engine is None:
            started = time.perf_counter()
            self._engine = RapidOCR()
            LOGGER.info("RapidOCR models initialized in %.0f ms", (time.perf_counter() - started) * 1000)
        return self._engine

    @staticmethod
    def _output_detections(output: object) -> list[TextDetection]:
        raw_texts = getattr(output, "txts", ())
        raw_scores = getattr(output, "scores", ())
        raw_boxes = getattr(output, "boxes", ())
        texts = list(raw_texts) if raw_texts is not None else []
        scores = list(raw_scores) if raw_scores is not None else []
        boxes = list(raw_boxes) if raw_boxes is not None else []
        detections: list[TextDetection] = []
        for index, text in enumerate(texts):
            if text is None:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            box = np.asarray(boxes[index], dtype=np.float32) if index < len(boxes) else None
            detections.append(TextDetection(str(text), score, box))
        return detections

    def _detect(self, image: np.ndarray) -> list[TextDetection]:
        output = self.engine(image, use_det=True, use_cls=False, use_rec=True)
        return self._output_detections(output)

    def _recognize(self, image: np.ndarray) -> list[TextDetection]:
        output = self.engine(image, use_det=False, use_cls=False, use_rec=True)
        return self._output_detections(output)

    @staticmethod
    def _join_line_candidates(detections: list[TextDetection]) -> list[TextDetection]:
        """Recover a plate if OCR finds individual adjacent character groups."""
        with_boxes = [item for item in detections if item.box is not None]
        if len(with_boxes) < 2:
            return []
        centers = [float(np.mean(item.box[:, 1])) for item in with_boxes]
        median_y = float(np.median(centers))
        heights = [max(1, cv2.boundingRect(item.box)[3]) for item in with_boxes]
        tolerance = max(12.0, float(np.median(heights)) * 0.8)
        same_line = [item for item, center in zip(with_boxes, centers, strict=True) if abs(center - median_y) <= tolerance]
        if len(same_line) < 2:
            return []
        same_line.sort(key=lambda item: cv2.boundingRect(item.box)[0])
        text = "".join(item.text for item in same_line)
        score = float(np.mean([item.score for item in same_line]))
        all_points = np.concatenate([item.box for item in same_line])
        x, y, width, height = cv2.boundingRect(all_points)
        box = np.array([[x, y], [x + width, y], [x + width, y + height], [x, y + height]], dtype=np.float32)
        return [TextDetection(text, score, box)]

    def analyze(self, search_image: np.ndarray) -> RecognitionResult:
        if search_image is None or search_image.size == 0:
            return RecognitionResult(ResultStatus.ERROR, message="Geçersiz görüntü")
        started = time.perf_counter()
        observations: list[Observation] = []
        raw_readings: list[str] = []
        crops: list[tuple[np.ndarray, float, str]] = []
        timings: dict[str, float] = {}

        try:
            detection_start = time.perf_counter()
            detections = self._detect(search_image)
            # A second detection pass is useful for headlight glare, but only when the
            # normal image produced no syntactically plausible text. This saves a full
            # model invocation on the common case.
            if not any(parse_candidates(item.text) for item in detections):
                gray = cv2.cvtColor(search_image, cv2.COLOR_BGR2GRAY)
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
                detections.extend(self._detect(cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)))
            detections.extend(self._join_line_candidates(detections))
            raw_readings.extend(item.text for item in detections if item.text.strip())
            timings["detection"] = (time.perf_counter() - detection_start) * 1000
        except Exception as error:  # OCR library errors are surfaced safely to the operator.
            LOGGER.exception("Detection failed")
            return RecognitionResult(ResultStatus.ERROR, message=f"OCR algılayıcı hatası: {error}")

        seen_crops: set[tuple[int, int, int, int]] = set()
        for detection in detections:
            # The detector's own line recognition may already be usable.
            self._collect_parsed(
                observations,
                detection.text,
                detection.score,
                "detector",
                detection.geometry_score,
            )
            if detection.box is None:
                continue
            x, y, width, height = cv2.boundingRect(np.asarray(detection.box, dtype=np.float32))
            identity = (x, y, width, height)
            if identity in seen_crops:
                continue
            seen_crops.add(identity)
            try:
                crops.append((crop_quad(search_image, detection.box), detection.geometry_score, "detected"))
            except ValueError:
                continue

        # A full search-band fallback means a weak detector cannot block recognition entirely.
        if not crops:
            crops.append((search_image, 0.45, "search_band"))

        recognition_start = time.perf_counter()
        for crop, geometry_score, origin in crops[:6]:
            for variant in preprocessing_variants(crop):
                try:
                    readings = self._recognize(variant.image)
                except Exception:
                    LOGGER.exception("Recognition failed for variant %s", variant.name)
                    continue
                for reading in readings:
                    if reading.text.strip():
                        raw_readings.append(reading.text)
                    self._collect_parsed(
                        observations,
                        reading.text,
                        reading.score,
                        f"{origin}:{variant.name}",
                        geometry_score,
                    )
        timings["recognition"] = (time.perf_counter() - recognition_start) * 1000
        timings["total"] = (time.perf_counter() - started) * 1000
        result = self._aggregate(observations, timings)
        if result.status == ResultStatus.NO_READ:
            result.raw_readings = list(dict.fromkeys(raw_readings))[:8]
        return result

    @staticmethod
    def _collect_parsed(
        observations: list[Observation], raw_text: str, ocr_score: float, variant: str, geometry_score: float
    ) -> None:
        # A single OCR pass must not vote for mutually exclusive legal plate shapes.
        # parse_candidates orders context-aware alternatives by correction cost and
        # format plausibility; cross-variant consensus is handled in _aggregate.
        parsed_candidates = parse_candidates(raw_text)
        if parsed_candidates:
            parsed = parsed_candidates[0]
            observations.append(
                Observation(
                    plate=parsed.canonical,
                    raw_text=raw_text,
                    ocr_score=max(0.0, min(1.0, float(ocr_score))),
                    variant=variant,
                    correction_count=parsed.correction_count,
                    geometry_score=geometry_score,
                )
            )

    @staticmethod
    def _aggregate(observations: Iterable[Observation], timings: dict[str, float]) -> RecognitionResult:
        grouped: dict[str, list[Observation]] = defaultdict(list)
        all_observations = list(observations)
        for observation in all_observations:
            grouped[observation.plate].append(observation)
        if not grouped:
            return RecognitionResult(
                ResultStatus.NO_READ,
                timings_ms=timings,
                message="Geçerli Türk plaka formatında bir sonuç bulunamadı.",
            )

        total_variants = max(1, len({item.variant for item in all_observations}))
        candidates: list[PlateCandidate] = []
        for plate, group in grouped.items():
            variants = sorted({item.variant for item in group})
            ocr_score = float(np.mean([item.ocr_score for item in group]))
            consensus = min(1.0, len(variants) / total_variants)
            geometry = float(np.mean([item.geometry_score for item in group]))
            corrections = min(item.correction_count for item in group)
            correction_penalty = min(0.12, corrections * 0.04)
            score = max(0.0, min(1.0, 0.45 * ocr_score + 0.30 * consensus + 0.20 + 0.05 * geometry - correction_penalty))
            candidates.append(
                PlateCandidate(
                    plate=plate,
                    score=score,
                    ocr_score=ocr_score,
                    variant_count=len(variants),
                    variant_names=variants,
                    raw_texts=sorted({item.raw_text for item in group}),
                    correction_count=corrections,
                    geometry_score=geometry,
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        best = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        is_high = best.score >= 0.90 and best.variant_count >= 2 and best.score - second_score >= 0.08
        return RecognitionResult(
            status=ResultStatus.HIGH_CONFIDENCE if is_high else ResultStatus.REVIEW,
            plate=best.plate,
            score=best.score,
            candidates=candidates[:3],
            winning_variant=best.variant_names[0] if best.variant_names else None,
            timings_ms=timings,
            message="Panoya kopyalandı." if is_high else "Sonucu gözle kontrol edip onaylayın.",
        )
