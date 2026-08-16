from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ResultStatus(StrEnum):
    HIGH_CONFIDENCE = "high_confidence"
    REVIEW = "review"
    NO_READ = "no_read"
    ERROR = "error"


@dataclass(frozen=True)
class NormalizedRect:
    """A rectangle whose values are fractions of its containing client rectangle."""

    left: float
    top: float
    width: float
    height: float

    def validate(self) -> None:
        values = (self.left, self.top, self.width, self.height)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("ROI values must stay between 0 and 1")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ROI width and height must be positive")
        if self.left + self.width > 1 or self.top + self.height > 1:
            raise ValueError("ROI must remain inside its parent rectangle")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NormalizedRect":
        rect = cls(**{key: float(value[key]) for key in ("left", "top", "width", "height")})
        rect.validate()
        return rect


@dataclass(frozen=True)
class PixelRect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Pixel ROI width and height must be positive")


@dataclass(frozen=True)
class WindowMatcher:
    title_contains: str = ""
    process_id: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "WindowMatcher | None":
        if not value:
            return None
        process_id = value.get("process_id")
        return cls(
            title_contains=str(value.get("title_contains", "")),
            process_id=int(process_id) if process_id else None,
        )


@dataclass
class PlateCandidate:
    plate: str
    score: float
    ocr_score: float
    variant_count: int
    variant_names: list[str] = field(default_factory=list)
    raw_texts: list[str] = field(default_factory=list)
    correction_count: int = 0
    geometry_score: float = 1.0


@dataclass
class RecognitionResult:
    status: ResultStatus
    plate: str | None = None
    score: float = 0.0
    candidates: list[PlateCandidate] = field(default_factory=list)
    winning_variant: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    message: str = ""
    # Test-only consumers may show these transient OCR fragments when no
    # syntactically valid plate was found.  They are never persisted unless
    # the operator separately enables diagnostics.
    raw_readings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result
