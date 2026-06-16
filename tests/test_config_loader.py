from music2db_client import config_loader
from music2db_client.settings import MusicSettings, Settings


def test_config_search_dirs_prefers_xdg(monkeypatch, tmp_path):
    xdg_dir = tmp_path / "xdg"
    cwd = tmp_path / "cwd"
    xdg_config_dir = xdg_dir / "music2db-client"
    local_config_dir = cwd / "config"

    for directory in (xdg_config_dir, cwd, local_config_dir):
        directory.mkdir(parents=True)
        (directory / "config.yaml").write_text("music:\n  path: /music\n", encoding="utf-8")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))

    files = config_loader.resolve_config_files("music2db-client", None, cwd=cwd)

    assert files == [str(xdg_config_dir / "config.yaml")]


def test_logging_config_ignores_rich_handler_legacy_keys(tmp_path):
    settings = Settings(
        music=MusicSettings(path=tmp_path),
        logging={"level": "DEBUG", "format": "%(message)s", "markup": True, "show_path": False},
    )

    config = config_loader.load_logging_config(settings, "music2db-client", cwd=tmp_path)

    assert config["level"] == "DEBUG"
    assert config["show_path"] is False
    assert "format" not in config
    assert "markup" not in config
