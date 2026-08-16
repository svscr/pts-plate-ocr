from __future__ import annotations

import json
import logging
import shutil
import time

import cv2
import numpy as np

from .config import APP_NAME, AppConfig, app_data_dir
from .models import RecognitionResult

LOGGER = logging.getLogger(__name__)


class Diagnostics:
    def __init__(self, config: AppConfig, *, app_name: str = APP_NAME) -> None:
        self.config = config
        self.root = app_data_dir(app_name) / "debug"

    def record(
        self,
        photo: np.ndarray,
        search_band: np.ndarray,
        result: RecognitionResult,
    ) -> None:
        if not self.config.debug.enabled:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        bundle = self.root / time.strftime("%Y%m%d-%H%M%S")
        bundle.mkdir(exist_ok=True)
        cv2.imwrite(str(bundle / "photo.png"), photo)
        cv2.imwrite(str(bundle / "search_band.png"), search_band)
        (bundle / "result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.cleanup()

    def cleanup(self) -> None:
        if not self.root.exists():
            return
        now = time.time()
        max_age = self.config.debug.retention_days * 24 * 60 * 60
        bundles = sorted((path for path in self.root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
        for bundle in bundles:
            if now - bundle.stat().st_mtime > max_age:
                shutil.rmtree(bundle, ignore_errors=True)
        limit = self.config.debug.max_megabytes * 1024 * 1024
        bundles = sorted((path for path in self.root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
        total = sum(file.stat().st_size for bundle in bundles for file in bundle.rglob("*") if file.is_file())
        for bundle in bundles:
            if total <= limit:
                break
            size = sum(file.stat().st_size for file in bundle.rglob("*") if file.is_file())
            shutil.rmtree(bundle, ignore_errors=True)
            total -= size
