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
AUTOMATION_TEST_APP_NAME = "PTSPlateOCRAutomationTest"
SCHEMA_VERSION = 5


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
class AutomationConfig:
    """Configuration used only by the separately packaged automation test build.

    The defaults were measured from the supplied ParkMatik screenshots.  Every
    coordinate is relative to the window it belongs to, so the test build can
    be calibrated without altering the normal OCR application's ROI settings.
    """

    enabled: bool = True
    main_window_title_contains: str = "ParkMatik"
    ticket_window_title_contains: str = "Bilet Sorgulama"
    image_dialog_title_contains: str = "Bilet Resimleri"
    plate_dialog_title_contains: str = "Plaka Değiştirme"
    ticket_grid_roi: NormalizedRect = field(
        default_factory=lambda: NormalizedRect(0.004, 0.175, 0.992, 0.360)
    )
    entrance_photo_roi: NormalizedRect = field(
        default_factory=lambda: NormalizedRect(0.012, 0.105, 0.480, 0.790)
    )
    entrance_plate_search_roi: NormalizedRect = field(
        default_factory=lambda: NormalizedRect(0.20, 0.18, 0.55, 0.42)
    )
    # Used only if the legacy PTS dialog does not expose an editable native
    # control that can be safely focused.
    plate_input_roi: NormalizedRect = field(
        default_factory=lambda: NormalizedRect(0.080, 0.120, 0.840, 0.230)
    )
    ticket_row_click_x: float = 0.56
    timeout_seconds: int = 6

    def validate(self) -> None:
        if not self.main_window_title_contains.strip():
            raise ValueError("PTS ana pencere başlığı boş olamaz.")
        if not self.ticket_window_title_contains.strip():
            raise ValueError("Bilet Sorgulama pencere başlığı boş olamaz.")
        if not self.image_dialog_title_contains.strip():
            raise ValueError("Görsel pencere başlığı boş olamaz.")
        if not self.plate_dialog_title_contains.strip():
            raise ValueError("Plaka penceresi başlığı boş olamaz.")
        for rect in (
            self.ticket_grid_roi,
            self.entrance_photo_roi,
            self.entrance_plate_search_roi,
            self.plate_input_roi,
        ):
            rect.validate()
        if not 0 < self.ticket_row_click_x < 1:
            raise ValueError("Bilet satırı tıklama noktası 0 ile 1 arasında olmalı.")
        if not 2 <= self.timeout_seconds <= 30:
            raise ValueError("Otomasyon zaman aşımı 2 ile 30 saniye arasında olmalı.")

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "AutomationConfig":
        source = raw or {}
        defaults = cls()
        return cls(
            enabled=bool(source.get("enabled", defaults.enabled)),
            main_window_title_contains=str(
                source.get("main_window_title_contains", defaults.main_window_title_contains)
            ),
            ticket_window_title_contains=str(
                source.get("ticket_window_title_contains", defaults.ticket_window_title_contains)
            ),
            image_dialog_title_contains=str(
                source.get("image_dialog_title_contains", defaults.image_dialog_title_contains)
            ),
            plate_dialog_title_contains=str(
                source.get("plate_dialog_title_contains", defaults.plate_dialog_title_contains)
            ),
            ticket_grid_roi=NormalizedRect.from_dict(
                source.get("ticket_grid_roi", asdict(defaults.ticket_grid_roi))
            ),
            entrance_photo_roi=NormalizedRect.from_dict(
                source.get("entrance_photo_roi", asdict(defaults.entrance_photo_roi))
            ),
            entrance_plate_search_roi=NormalizedRect.from_dict(
                source.get("entrance_plate_search_roi", asdict(defaults.entrance_plate_search_roi))
            ),
            plate_input_roi=NormalizedRect.from_dict(
                source.get("plate_input_roi", asdict(defaults.plate_input_roi))
            ),
            ticket_row_click_x=float(source.get("ticket_row_click_x", defaults.ticket_row_click_x)),
            timeout_seconds=int(source.get("timeout_seconds", defaults.timeout_seconds)),
        )


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
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    popup_timeout_seconds: int = 8

    def validate(self) -> None:
        self.desktop_photo_roi.validate()
        self.plate_search_roi.validate()
        if self.photo_roi_relative_to_window:
            self.photo_roi_relative_to_window.validate()
        self.hotkey = normalize_hotkey(self.hotkey)
        if not 0 < self.confidence.high_score <= 1:
            raise ValueError("high_score must be between 0 and 1")
        self.automation.validate()

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
            migrated["schema_version"] = SCHEMA_VERSION
            automation = dict(migrated.get("automation") or {})
            if float(automation.get("ticket_row_click_x", 0.12)) == 0.12:
                automation["ticket_row_click_x"] = AutomationConfig().ticket_row_click_x
            migrated["automation"] = automation
        elif source_schema_version in (2, 3, 4):
            automation = dict(migrated.get("automation") or {})
            if float(automation.get("ticket_row_click_x", 0.12)) == 0.12:
                automation["ticket_row_click_x"] = AutomationConfig().ticket_row_click_x
            migrated["automation"] = automation
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
            automation=AutomationConfig.from_dict(migrated.get("automation")),
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
