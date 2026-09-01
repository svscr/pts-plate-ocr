from pathlib import Path

from pts_plate_ocr.config import AppConfig, ConfigStore, normalized_to_pixels
from pts_plate_ocr.models import NormalizedRect, PixelRect


def test_default_is_ctrl_alt_p() -> None:
    assert AppConfig().hotkey == "Ctrl+Alt+P"


def test_normalized_rect_conversion() -> None:
    rect = normalized_to_pixels(NormalizedRect(0.25, 0.5, 0.5, 0.25), PixelRect(100, 200, 800, 400))
    assert rect == PixelRect(300, 400, 400, 100)


def test_store_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    config = AppConfig(hotkey="Ctrl+Alt+O")
    store.save(config)
    assert store.load().hotkey == "Ctrl+Alt+O"


def test_legacy_f7_config_migrates_without_losing_other_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"schema_version": 1, "hotkey": "F7"}', encoding="utf-8")
    config = ConfigStore(path).load()
    assert config.hotkey == "Ctrl+Alt+P"
    assert '"schema_version": 6' in path.read_text(encoding="utf-8")


def test_legacy_automation_settings_are_removed(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        '{"schema_version": 5, "hotkey": "Ctrl+Alt+O", '
        '"automation": {"enabled": true}}',
        encoding="utf-8",
    )
    config = ConfigStore(path).load()
    saved = path.read_text(encoding="utf-8")
    assert config.hotkey == "Ctrl+Alt+O"
    assert '"schema_version": 6' in saved
    assert "automation" not in saved
