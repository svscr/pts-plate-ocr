from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from .models import NormalizedRect, PixelRect, WindowMatcher
from .shortcuts import DEFAULT_HOTKEY, normalize_hotkey

LOGGER = logging.getLogger(__name__)
APP_NAME = "PTSPlateOCR"
SCHEMA_VERSION = 6


@dataclass
class ConfidenceConfig:
    high_score: float = 0.90
    minimum_margin: float = 0.08
    minimum_agreeing_variants: int = 2


@dataclass
class DebugConfig:
    enabled: bool = False
    retention_days: int = 7
    max_megabytes: int = 500


@dataclass
class AppConfig:
    schema_version: int = SCHEMA_VERSION
    hotkey: str = DEFAULT_HOTKEY
    # Preset inferred from the supplied 1920x1080 ParkMatik screenshot.
    desktop_photo_roi: NormalizedRect = field(
        default_factory=lambda: NormalizedRect(0.1604, 0.3324, 0.3333, 0.3333)
    )
    # Wide, central band: it is intentionally not a tight plate crop.
    plate_search_roi: NormalizedRect = field(
        default_factory=lambda: NormalizedRect(0.20, 0.18, 0.55, 0.42)
    )
    window_matcher: WindowMatcher | None = None
    photo_roi_relative_to_window: NormalizedRect | None = None
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    popup_timeout_seconds: int = 8

    def validate(self) -> None:
        self.desktop_photo_roi.validate()
        self.plate_search_roi.validate()
        if self.photo_roi_relative_to_window:
            self.photo_roi_relative_to_window.validate()
        self.hotkey = normalize_hotkey(self.hotkey)
        if not 0 < self.confidence.high_score <= 1:
            raise ValueError("high_score must be between 0 and 1")
        if not 0 <= self.confidence.minimum_margin <= 1:
            raise ValueError("minimum_margin must be between 0 and 1")
        if self.confidence.minimum_agreeing_variants < 1:
            raise ValueError("minimum_agreeing_variants must be at least 1")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        migrated = dict(raw)
        source_schema_version = int(migrated.get("schema_version", 1))
        if source_schema_version == 1:
            # Earlier builds only offered F1-F12 and defaulted to F7.  Move that
            # implicit default to a modifier combination while preserving user
            # calibration and any deliberately chosen non-F7 function key.
            if str(migrated.get("hotkey", "F7")).strip().upper() == "F7":
                migrated["hotkey"] = DEFAULT_HOTKEY
        if source_schema_version in (1, 2, 3, 4, 5):
            # Schema 6 removes abandoned PTS automation settings while retaining
            # the OCR hotkey and calibration fields loaded below.
            migrated["schema_version"] = SCHEMA_VERSION
        elif source_schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported config schema")
        config = cls(
            schema_version=SCHEMA_VERSION,
            hotkey=str(migrated.get("hotkey", DEFAULT_HOTKEY)),
            desktop_photo_roi=NormalizedRect.from_dict(
                migrated.get("desktop_photo_roi", asdict(cls().desktop_photo_roi))
            ),
            plate_search_roi=NormalizedRect.from_dict(
                migrated.get("plate_search_roi", asdict(cls().plate_search_roi))
            ),
            window_matcher=WindowMatcher.from_dict(migrated.get("window_matcher")),
            photo_roi_relative_to_window=(
                NormalizedRect.from_dict(migrated["photo_roi_relative_to_window"])
                if migrated.get("photo_roi_relative_to_window")
                else None
            ),
            confidence=ConfidenceConfig(**migrated.get("confidence", {})),
            debug=DebugConfig(**migrated.get("debug", {})),
            popup_timeout_seconds=int(migrated.get("popup_timeout_seconds", 8)),
        )
        config.validate()
        return config

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def app_data_dir(app_name: str = APP_NAME) -> Path:
    path = Path(user_data_path(app_name, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path(app_name: str = APP_NAME) -> Path:
    return app_data_dir(app_name) / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None, app_name: str = APP_NAME) -> None:
        self.app_name = app_name
        self.path = path or config_path(app_name)

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = AppConfig()
            self.save(config)
            return config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("config root must be an object")
            config = AppConfig.from_dict(raw)
            if int(raw.get("schema_version", 1)) != SCHEMA_VERSION or raw.get("hotkey") != config.hotkey:
                self.save(config)
            return config
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            backup = self.path.with_suffix(".invalid.json")
            try:
                self.path.replace(backup)
            except OSError:
                LOGGER.exception("Could not back up invalid config")
            LOGGER.warning("Invalid config was replaced: %s", error)
            config = AppConfig()
            self.save(config)
            return config

    def save(self, config: AppConfig) -> None:
        config.validate()
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


def normalized_to_pixels(rect: NormalizedRect, parent: PixelRect) -> PixelRect:
    result = PixelRect(
        left=parent.left + round(rect.left * parent.width),
        top=parent.top + round(rect.top * parent.height),
        width=max(1, round(rect.width * parent.width)),
        height=max(1, round(rect.height * parent.height)),
    )
    result.validate()
    return result
