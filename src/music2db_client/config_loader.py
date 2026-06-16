from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .settings import Settings


HOME_DIR = os.path.expanduser("~")
ACTIVE_CONFIG_FILES: list[Path] = []


def default_logging_config() -> dict[str, Any]:
    return {
        "level": "INFO",
        "console": True,
        "file_enabled": False,
        "file": "logs/music2db-client.log",
        "show_time": True,
        "time_format": "%H:%M:%S",
        "show_level": False,
        "show_path": False,
        "logs_width": 140,
        "tags_width": 16,
        "tag_filter_mode": "any",
        "unknown_tags": "hide",
        "show_all_tags_errors": True,
        "show_all_tags_warnings": True,
        "level_decor": {
            "notset": {"symbol": "█"},
            "debug": {"symbol": "█"},
            "info": {"symbol": "█"},
            "warning": {"symbol": "█"},
            "error": {"symbol": "█"},
            "critical": {"symbol": "█"},
        },
        "loggers": {
            "httpx": "WARNING",
            "httpcore": "WARNING",
            "requests": "WARNING",
            "urllib3.connectionpool": "WARNING",
            "mutagen": "WARNING",
            "schedule": "WARNING",
        },
        "tags": {
            "startup": {"show": True, "icon": "S", "tag_color": "#5f875f", "icon_color": "#ffffff"},
            "config": {"show": True, "icon": "cfg", "tag_color": "#5f5f87", "icon_color": "#ffffff"},
            "scan": {"show": True, "icon": "scan", "tag_color": "#005f87", "icon_color": "#ffffff"},
            "metadata": {"show": False, "icon": "meta", "tag_color": "#008787", "icon_color": "#ffffff"},
            "http": {"show": False, "icon": "http", "tag_color": "#444444", "icon_color": "#ffffff"},
            "state": {"show": True, "icon": "st", "tag_color": "#875f00", "icon_color": "#ffffff"},
        },
    }


def config_search_dirs(app_name: str, cwd: Path | None = None) -> list[Path]:
    current_dir = cwd or Path.cwd()
    xdg_root = Path(os.getenv("XDG_CONFIG_HOME", os.path.join(HOME_DIR, ".config")))
    return [
        xdg_root / app_name,
        Path("/etc") / app_name,
        current_dir,
        current_dir / "config",
    ]


def discover_config_files(app_name: str, filename: str, cwd: Path | None = None) -> list[str]:
    return [
        str(path / filename)
        for path in config_search_dirs(app_name, cwd=cwd)
        if (path / filename).exists()
    ]


def resolve_config_files(app_name: str, config_file: str | None, cwd: Path | None = None) -> list[str]:
    if config_file:
        return [str(Path(config_file).expanduser())]
    discovered = discover_config_files(app_name, "config.yaml", cwd=cwd)
    return discovered[:1]


def set_active_config_files(files: list[str]) -> None:
    global ACTIVE_CONFIG_FILES
    ACTIVE_CONFIG_FILES = [Path(file).expanduser() for file in files]


def get_active_config_files() -> list[Path]:
    return list(ACTIVE_CONFIG_FILES)


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(config_files: list[str]) -> Settings:
    raw_config: dict[str, Any] = {}
    for config_file in config_files:
        config_path = Path(config_file).expanduser()
        if not config_path.exists():
            continue
        with config_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        raw_config = merge_dicts(raw_config, loaded)
    return Settings.model_validate(raw_config)


def resolve_logging_config_file(cfg: Settings, app_name: str, cwd: Path | None = None) -> Path | None:
    explicit_path = cfg.app.logging_config
    if explicit_path:
        return Path(explicit_path).expanduser()

    for config_file in ACTIVE_CONFIG_FILES:
        logging_path = config_file.parent / "logging.yaml"
        if logging_path.exists():
            return logging_path

    for candidate in config_search_dirs(app_name, cwd=cwd):
        logging_path = candidate / "logging.yaml"
        if logging_path.exists():
            return logging_path

    return None


def load_logging_config(cfg: Settings, app_name: str, cwd: Path | None = None) -> dict[str, Any]:
    config = default_logging_config()
    legacy_logging = getattr(cfg, "logging", {})
    if isinstance(legacy_logging, dict):
        legacy_subset = {
            key: legacy_logging[key]
            for key in ("level", "show_time", "show_path")
            if key in legacy_logging
        }
        config = merge_dicts(config, legacy_subset)

    logging_path = resolve_logging_config_file(cfg, app_name, cwd=cwd)
    if logging_path and logging_path.exists():
        with logging_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        config = merge_dicts(config, loaded)

    return config
