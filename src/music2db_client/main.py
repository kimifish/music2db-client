from __future__ import annotations

import argparse
import json
import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import requests
import schedule
from dotenv import load_dotenv
from mutagen import File as MutagenFile  # type: ignore
from pydantic import ValidationError

from .config_loader import (
    get_active_config_files,
    load_logging_config,
    load_settings,
    resolve_config_files,
    resolve_logging_config_file,
    set_active_config_files,
)
from .logging_setup import get_logger, setup_logging
from .settings import Settings
from .signals import GracefulKiller

APP_NAME = "music2db-client"
HOME_DIR = os.path.expanduser("~")

load_dotenv()

log = get_logger(__name__)
settings: Settings


def extract_metadata(file_path: Path) -> dict[str, Any]:
    """Extract contract-compatible metadata from a music file."""
    audio = MutagenFile(file_path)
    if audio is None:
        return {}

    metadata: dict[str, Any] = {}
    tags = audio.tags
    if hasattr(audio, "info") and hasattr(audio.info, "length"):
        metadata["length"] = int(audio.info.length)

    if tags:
        if hasattr(tags, "getall"):
            metadata["artist"] = _join_id3_text(tags.getall("TPE1"))
            metadata["title"] = _join_id3_text(tags.getall("TIT2"))
            metadata["album"] = _join_id3_text(tags.getall("TALB"))
            metadata["genre"] = _join_id3_text(tags.getall("TCON"))
            metadata["year"] = _join_id3_text(tags.getall("TDRC"))

            for comm in tags.getall("COMM"):
                if comm.desc == "LastFM tags" and comm.text:
                    metadata["tags"] = str(comm.text[0]).replace("LastFM tags:", "").strip()
                    break
        else:
            metadata["artist"] = _first_tag_value(tags, "artist")
            metadata["title"] = _first_tag_value(tags, "title")
            metadata["album"] = _first_tag_value(tags, "album")
            metadata["genre"] = _first_tag_value(tags, "genre")
            metadata["year"] = _first_tag_value(tags, "date")

            comment = _first_tag_value(tags, "comment")
            if isinstance(comment, str) and "LastFM tags:" in comment:
                metadata["tags"] = comment.split("LastFM tags:", 1)[1].strip()

    return sanitize_metadata(metadata)


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    cleaned: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        normalized = _to_json_primitive(value)
        if normalized is not None:
            cleaned[key] = normalized
    return cleaned


def check_server_health() -> bool:
    """Check whether the server is ready for indexing."""
    url = f"{settings.music_db.base_url}/health/"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            log.error("`http` Server health check failed with status code %s", response.status_code)
            return False

        data = response.json()
        if data.get("status") != "Server is running":
            log.error("`http` Invalid server health response: %s", data)
            return False
        if data.get("chromadb") != "ok":
            log.error("`http` ChromaDB is not ready: %s", data.get("chromadb"))
            return False
        if data.get("embeddings") != "ok":
            log.error("`http` Embeddings service is not ready: %s", data.get("embeddings"))
            return False

        if data.get("embedding_model"):
            log.info("`http` Server embedding model: %s", data["embedding_model"])
        return True
    except requests.exceptions.RequestException as exc:
        log.error("`http` Server health check failed: %s", exc)
        return False
    except ValueError as exc:
        log.error("`http` Server health response is not JSON: %s", exc)
        return False


def scan_music_directory(killer: GracefulKiller, force: bool = False) -> bool:
    """Scan music directory and send metadata to the server."""
    if not check_server_health():
        log.error("`scan` Server is not healthy, skipping scan")
        return False

    music_path = settings.music.path.expanduser()
    if not music_path.exists():
        log.error("`scan` Music directory does not exist: %s", music_path)
        return False

    last_scan_time = _get_last_scan_time()
    latest_modification = _get_latest_modification(music_path)
    if not force and latest_modification <= last_scan_time:
        log.info("`scan` No changes in music library since last scan, skipping")
        return True

    log.info("`scan` Starting music directory scan: %s", music_path)

    extensions = {extension.lower() for extension in settings.music.extensions}
    batch: list[dict[str, Any]] = []
    ignored_dirs = {path.parent for path in music_path.rglob(".ignore")}
    stats = {"files": 0, "tracks": 0, "metadata_errors": 0, "upload_errors": 0, "ignored_dirs": len(ignored_dirs)}

    for file_path in music_path.rglob("*"):
        if killer.kill_now:
            log.info("`scan` Termination requested, stopping scan")
            return False

        try:
            if file_path.is_symlink() or not file_path.is_file():
                continue
            if any(parent in ignored_dirs for parent in file_path.parents):
                continue
            if file_path.suffix.lower() not in extensions:
                continue

            stats["files"] += 1
            metadata = extract_metadata(file_path)
            if not metadata:
                continue

            batch.append({"file_path": str(file_path.relative_to(music_path)), "metadata": metadata})
            stats["tracks"] += 1

            if len(batch) >= settings.scan.batch_size:
                if not _send_batch(batch):
                    stats["upload_errors"] += 1
                batch = []
        except Exception as exc:
            stats["metadata_errors"] += 1
            log.error("`metadata` Error processing %s: %s", file_path, exc)

    if batch and not _send_batch(batch):
        stats["upload_errors"] += 1

    log.info(
        "`scan` Scan finished: files=%s tracks=%s ignored_dirs=%s metadata_errors=%s upload_errors=%s",
        stats["files"],
        stats["tracks"],
        stats["ignored_dirs"],
        stats["metadata_errors"],
        stats["upload_errors"],
    )

    if stats["upload_errors"] == 0 and not killer.kill_now:
        _save_last_scan_time(time.time())
        return True
    return False


def _send_batch(tracks: list[dict[str, Any]]) -> bool:
    url = f"{settings.music_db.base_url}{settings.music_db.many_tracks_endpoint}"
    last_error = "unknown error"

    for attempt in range(1, settings.music_db.retry_count + 1):
        try:
            log.info("`http` Sending batch of %s tracks to server", len(tracks))
            response = requests.post(url, json=tracks, timeout=settings.music_db.timeout_seconds)

            if response.status_code == 200:
                result = response.json()
                errors = result.get("errors") if isinstance(result, dict) else None
                if isinstance(result, dict) and result.get("message"):
                    log.info("`http` %s", result["message"])
                if errors:
                    log.error("`http` Batch completed with %s per-track errors", len(errors))
                    for error in errors[:10]:
                        log.error("`http` Batch item error: %s", error)
                    return False
                return True

            detail = _response_detail(response)
            last_error = f"HTTP {response.status_code}: {detail}"
            if response.status_code == 503 and attempt < settings.music_db.retry_count:
                _sleep_before_retry(attempt)
                continue

            log.error("`http` Failed to send batch: %s", last_error)
            return False
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
            if attempt < settings.music_db.retry_count:
                _sleep_before_retry(attempt)
                continue
            log.error("`http` Error sending batch to server: %s", exc)
            return False
        except ValueError as exc:
            log.error("`http` Batch response is not JSON: %s", exc)
            return False

    log.error("`http` Failed to send batch after retries: %s", last_error)
    return False


def _get_last_scan_time() -> float:
    state_file = _state_file()
    if state_file.exists():
        try:
            with state_file.open("r", encoding="utf-8") as file:
                state = json.load(file)
            return float(state.get("last_scan_time", 0))
        except Exception as exc:
            log.error("`state` Error reading state file: %s", exc)
    return 0


def _save_last_scan_time(timestamp: float) -> None:
    state_file = _state_file()
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with state_file.open("w", encoding="utf-8") as file:
            json.dump({"last_scan_time": timestamp}, file)
    except Exception as exc:
        log.error("`state` Error saving state file: %s", exc)


def _get_latest_modification(directory: Path) -> float:
    latest = directory.stat().st_mtime
    try:
        for entry in directory.rglob("*"):
            if entry.is_file() and not entry.is_symlink():
                latest = max(latest, entry.stat().st_mtime)
    except Exception as exc:
        log.error("`state` Error checking modifications: %s", exc)
    return latest


def _state_file() -> Path:
    return Path(os.getenv("XDG_STATE_HOME", os.path.join(HOME_DIR, ".local/state"))) / APP_NAME / "state.json"


def _join_id3_text(frames: list[Any]) -> str | None:
    values = []
    for frame in frames:
        text = getattr(frame, "text", None)
        if text:
            values.append(str(text[0]))
    return " & ".join(values) if values else None


def _first_tag_value(tags: Any, key: str) -> Any:
    value = tags.get(key, [None])
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _to_json_primitive(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | str):
        return value
    return str(value)


def _response_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict) and "detail" in payload:
            return str(payload["detail"])
        return str(payload)
    except ValueError:
        return response.text


def _sleep_before_retry(attempt: int) -> None:
    delay = settings.music_db.retry_backoff_seconds * attempt
    log.warning("`http` Retrying batch after %.1f seconds", delay)
    time.sleep(delay)


def _parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Music2DB Client")
    parser.add_argument("-c", "--config", dest="config_file", default=None, help="Configuration file location.")
    parser.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {_package_version()}")
    parser.add_argument("--run-once", action="store_true", help="Run the scan once and exit.")
    parser.add_argument("--dont-scan-now", action="store_true", help="Don't run the scan immediately.")
    parser.add_argument("--force-rescan", action="store_true", help="Ignore saved scan timestamp and reindex files.")
    return parser.parse_known_args()


def _init_config(config_file: str | None) -> None:
    global settings
    config_files = resolve_config_files(APP_NAME, config_file)
    if not config_files:
        print(
            f"No config.yaml found for {APP_NAME}. Checked XDG config, /etc, ./config.yaml and ./config/config.yaml",
            file=sys.stderr,
        )
        raise SystemExit(1)
    set_active_config_files(config_files)
    try:
        settings = load_settings(config_files)
    except ValidationError as exc:
        print(f"Invalid configuration for {APP_NAME}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _init_logs() -> None:
    logging_config = load_logging_config(settings, APP_NAME)
    setup_logging(logging_config)
    log.info("`config` Logging configured from %s", str(resolve_logging_config_file(settings, APP_NAME) or "<defaults>"))
    if str(logging_config.get("level", "INFO")).upper() == "DEBUG":
        log.debug("`config` Active config files: %s", [str(path) for path in get_active_config_files()])


def _package_version() -> str:
    try:
        return version("music2db-client")
    except PackageNotFoundError:
        return "0.3.2"


def main() -> int:
    args, _unknown_args = _parse_args()
    _init_config(args.config_file)
    _init_logs()

    killer = GracefulKiller(kill_targets=[schedule.clear])
    log.info("`startup` Starting %s", APP_NAME)
    schedule.every().day.at(settings.music.scan_time).do(scan_music_directory, killer)

    if not args.dont_scan_now:
        scan_music_directory(killer, force=args.force_rescan)

    if args.run_once:
        log.info("`startup` Run once flag set, exiting")
        return 0

    while not killer.kill_now:
        schedule.run_pending()
        time.sleep(15)

    log.info("`startup` Shutting down %s", APP_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
