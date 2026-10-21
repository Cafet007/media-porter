"""Tests for persisted UI settings."""

import pytest

import backend.utils.config as config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "_CONFIG_FILE", tmp_path / "config.toml")


def test_theme_defaults_to_system():
    assert config.get_theme_mode() == "system"


def test_theme_migrates_legacy_dark_mode_flag():
    config.save_dark_mode(True)
    assert config.get_theme_mode() == "dark"
    config.save_dark_mode(False)
    assert config.get_theme_mode() == "light"


def test_theme_mode_round_trip():
    config.save_theme_mode("dark")
    assert config.get_theme_mode() == "dark"
    config.save_theme_mode("system")
    assert config.get_theme_mode() == "system"


def test_theme_mode_rejects_unknown():
    with pytest.raises(ValueError):
        config.save_theme_mode("purple")


def test_auto_scan_default_and_round_trip():
    assert config.get_auto_scan() is True
    config.save_auto_scan(False)
    assert config.get_auto_scan() is False


def test_window_state_round_trip():
    assert config.get_window_state() == {}
    state = {"geometry": "AdnQywADAAA=", "sizes": [240, 700, 260],
             "show_drives": True, "show_destination": False, "file_view": "grid"}
    config.save_window_state(state)
    assert config.get_window_state() == state
