from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


@dataclass
class FileSnapshot:
    path: Path
    relative_path: str
    mtime: float
    size: int


@dataclass
class FileRecord:
    mtime: float
    size: int
    metadata_hash: str


@dataclass
class Manifest:
    version: int
    music_root: str
    last_scan: float
    last_server_audit: float
    files: dict[str, FileRecord]


@dataclass
class SyncPlan:
    tracks_to_send: list[dict[str, Any]]
    paths_to_delete: list[str]
    manifest: Manifest
    metadata_errors: int
    files_seen: int


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


def scan_music_directory(
    killer: GracefulKiller,
    force: bool = False,
    dry_run: bool | None = None,
    audit_server: bool = False,
    delete_missing: bool | None = None,
) -> bool:
    """Synchronize server state with the local music directory."""
    dry_run = settings.sync.dry_run if dry_run is None else dry_run
    delete_missing = settings.sync.delete_missing if delete_missing is None else delete_missing

    if not check_server_health():
        log.error("`scan` Server is not healthy, skipping scan")
        return False

    music_path = settings.music.path.expanduser()
    if not music_path.exists():
        log.error("`scan` Music directory does not exist: %s", music_path)
        return False

    log.info("`scan` Starting music directory sync: %s", music_path)
    manifest = _load_manifest(music_path)
    plan = _build_sync_plan(music_path, manifest, killer, force=force)

    if killer.kill_now:
        log.info("`scan` Termination requested, stopping sync")
        return False

    if not delete_missing:
        log.info("`scan` delete_missing is disabled; %s stale server IDs will be kept", len(plan.paths_to_delete))
        for relative_path in plan.paths_to_delete:
            old_record = manifest.files.get(relative_path)
            if old_record is not None:
                plan.manifest.files[relative_path] = old_record
        plan.paths_to_delete = []

    audit_due = _server_audit_due(manifest) or audit_server
    log.info(
        "`scan` Sync plan: files=%s send=%s delete=%s metadata_errors=%s audit=%s dry_run=%s",
        plan.files_seen,
        len(plan.tracks_to_send),
        len(plan.paths_to_delete),
        plan.metadata_errors,
        audit_due,
        dry_run,
    )

    if dry_run:
        _log_dry_run_plan(plan)
        return plan.metadata_errors == 0

    success = True
    if plan.tracks_to_send and not _send_tracks_in_batches(plan.tracks_to_send):
        success = False

    if plan.paths_to_delete and not _delete_tracks(plan.paths_to_delete):
        success = False

    if audit_due and success:
        success = _audit_server(plan, music_path, delete_missing=delete_missing)

    if success and plan.metadata_errors == 0 and not killer.kill_now:
        plan.manifest.last_scan = time.time()
        if audit_due:
            plan.manifest.last_server_audit = plan.manifest.last_scan
        _save_manifest(plan.manifest)
        return True

    log.error("`scan` Sync did not complete cleanly; manifest was not updated")
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


def _send_tracks_in_batches(tracks: list[dict[str, Any]]) -> bool:
    success = True
    for index in range(0, len(tracks), settings.scan.batch_size):
        if not _send_batch(tracks[index : index + settings.scan.batch_size]):
            success = False
    return success


def _delete_tracks(file_paths: list[str]) -> bool:
    success = True
    for file_path in file_paths:
        if not _delete_track(file_path):
            success = False
    return success


def _delete_track(file_path: str) -> bool:
    encoded_path = quote(file_path, safe="")
    url = f"{settings.music_db.base_url}{settings.music_db.delete_track_endpoint}?file_path={encoded_path}"
    try:
        response = requests.delete(url, timeout=settings.music_db.timeout_seconds)
        if response.status_code != 200:
            log.error("`http` Failed to delete track %s: HTTP %s: %s", file_path, response.status_code, _response_detail(response))
            return False
        result = response.json()
        if isinstance(result, dict):
            log.info("`http` Delete synced for %s: deleted=%s", file_path, result.get("deleted"))
        return True
    except requests.exceptions.RequestException as exc:
        log.error("`http` Error deleting track %s: %s", file_path, exc)
        return False
    except ValueError as exc:
        log.error("`http` Delete response is not JSON for %s: %s", file_path, exc)
        return False


def _list_server_tracks() -> set[str] | None:
    url = f"{settings.music_db.base_url}{settings.music_db.list_tracks_endpoint}"
    try:
        response = requests.get(url, timeout=settings.music_db.timeout_seconds)
        if response.status_code != 200:
            log.error("`http` Failed to list server tracks: HTTP %s: %s", response.status_code, _response_detail(response))
            return None
        result = response.json()
        tracks = result.get("tracks") if isinstance(result, dict) else None
        if not isinstance(tracks, list):
            log.error("`http` Invalid list_tracks response: %s", result)
            return None
        return {str(track) for track in tracks}
    except requests.exceptions.RequestException as exc:
        log.error("`http` Error listing server tracks: %s", exc)
        return None
    except ValueError as exc:
        log.error("`http` list_tracks response is not JSON: %s", exc)
        return None


def _audit_server(plan: SyncPlan, music_path: Path, delete_missing: bool = True) -> bool:
    server_tracks = _list_server_tracks()
    if server_tracks is None:
        return False

    local_tracks = set(plan.manifest.files)
    stale_server_tracks = sorted(server_tracks - local_tracks)
    missing_server_tracks = sorted(local_tracks - server_tracks)
    log.info(
        "`scan` Server audit: server=%s local=%s missing_on_server=%s stale_on_server=%s",
        len(server_tracks),
        len(local_tracks),
        len(missing_server_tracks),
        len(stale_server_tracks),
    )

    success = True
    if stale_server_tracks and delete_missing:
        success = _delete_tracks(stale_server_tracks) and success
    elif stale_server_tracks:
        log.info("`scan` delete_missing is disabled; %s stale server tracks found by audit were kept", len(stale_server_tracks))

    if missing_server_tracks:
        tracks_to_send = []
        for relative_path in missing_server_tracks:
            file_path = music_path / relative_path
            try:
                metadata = extract_metadata(file_path)
            except Exception as exc:
                log.error("`metadata` Error processing audit-missing file %s: %s", file_path, exc)
                success = False
                continue
            if metadata:
                tracks_to_send.append({"file_path": relative_path, "metadata": metadata})
        if tracks_to_send:
            success = _send_tracks_in_batches(tracks_to_send) and success

    return success


def _build_sync_plan(music_path: Path, manifest: Manifest, killer: GracefulKiller, force: bool = False) -> SyncPlan:
    inventory = _build_inventory(music_path, killer)
    current_paths = set(inventory)
    known_paths = set(manifest.files)
    paths_to_delete = sorted(known_paths - current_paths)
    tracks_to_send: list[dict[str, Any]] = []
    next_files: dict[str, FileRecord] = {}
    metadata_errors = 0

    for relative_path, snapshot in sorted(inventory.items()):
        old_record = manifest.files.get(relative_path)
        needs_metadata = force or old_record is None or old_record.mtime != snapshot.mtime or old_record.size != snapshot.size

        if not needs_metadata and old_record is not None:
            next_files[relative_path] = old_record
            continue

        try:
            metadata = extract_metadata(snapshot.path)
        except Exception as exc:
            metadata_errors += 1
            log.error("`metadata` Error processing %s: %s", snapshot.path, exc)
            if old_record is not None:
                next_files[relative_path] = old_record
            continue

        if not metadata:
            continue

        metadata_hash = _metadata_hash(metadata)
        next_record = FileRecord(mtime=snapshot.mtime, size=snapshot.size, metadata_hash=metadata_hash)
        next_files[relative_path] = next_record

        if force or old_record is None or old_record.metadata_hash != metadata_hash:
            tracks_to_send.append({"file_path": relative_path, "metadata": metadata})

    next_manifest = Manifest(
        version=1,
        music_root=str(music_path),
        last_scan=manifest.last_scan,
        last_server_audit=manifest.last_server_audit,
        files=next_files,
    )
    return SyncPlan(
        tracks_to_send=tracks_to_send,
        paths_to_delete=paths_to_delete,
        manifest=next_manifest,
        metadata_errors=metadata_errors,
        files_seen=len(inventory),
    )


def _build_inventory(music_path: Path, killer: GracefulKiller) -> dict[str, FileSnapshot]:
    extensions = {extension.lower() for extension in settings.music.extensions}
    ignored_dirs = {path.parent for path in music_path.rglob(".ignore")}
    inventory: dict[str, FileSnapshot] = {}

    for file_path in music_path.rglob("*"):
        if killer.kill_now:
            break
        if file_path.is_symlink() or not file_path.is_file():
            continue
        if any(parent in ignored_dirs for parent in file_path.parents):
            continue
        if file_path.suffix.lower() not in extensions:
            continue
        try:
            stat = file_path.stat()
        except OSError as exc:
            log.error("`state` Error stating %s: %s", file_path, exc)
            continue
        relative_path = str(file_path.relative_to(music_path))
        inventory[relative_path] = FileSnapshot(
            path=file_path,
            relative_path=relative_path,
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    log.info("`scan` Inventory built: files=%s ignored_dirs=%s", len(inventory), len(ignored_dirs))
    return inventory


def _metadata_hash(metadata: dict[str, Any]) -> str:
    payload = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _server_audit_due(manifest: Manifest) -> bool:
    interval_seconds = settings.sync.audit_interval_hours * 3600
    if interval_seconds <= 0:
        return True
    return time.time() - manifest.last_server_audit >= interval_seconds


def _log_dry_run_plan(plan: SyncPlan) -> None:
    log.info(
        "`scan` Dry run only: would_send=%s would_delete=%s files=%s metadata_errors=%s",
        len(plan.tracks_to_send),
        len(plan.paths_to_delete),
        plan.files_seen,
        plan.metadata_errors,
    )
    for track in plan.tracks_to_send[:20]:
        log.info("`scan` Would add/update: %s", track["file_path"])
    for file_path in plan.paths_to_delete[:20]:
        log.info("`scan` Would delete: %s", file_path)


def _load_manifest(music_path: Path) -> Manifest:
    state_file = _state_file()
    if not state_file.exists():
        return _empty_manifest(music_path)

    try:
        with state_file.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except Exception as exc:
        log.error("`state` Error reading state file: %s", exc)
        return _empty_manifest(music_path)

    if "files" not in raw:
        log.info("`state` Migrating legacy state file without manifest")
        return _empty_manifest(music_path)

    files = {}
    for relative_path, record in raw.get("files", {}).items():
        try:
            files[str(relative_path)] = FileRecord(
                mtime=float(record["mtime"]),
                size=int(record["size"]),
                metadata_hash=str(record["metadata_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("`state` Skipping invalid manifest record %s: %s", relative_path, exc)

    return Manifest(
        version=int(raw.get("version", 1)),
        music_root=str(raw.get("music_root", music_path)),
        last_scan=float(raw.get("last_scan", 0)),
        last_server_audit=float(raw.get("last_server_audit", 0)),
        files=files,
    )


def _save_manifest(manifest: Manifest) -> None:
    state_file = _state_file()
    tmp_file = state_file.with_suffix(".tmp")
    payload = {
        "version": manifest.version,
        "music_root": manifest.music_root,
        "last_scan": manifest.last_scan,
        "last_server_audit": manifest.last_server_audit,
        "files": {relative_path: asdict(record) for relative_path, record in sorted(manifest.files.items())},
    }
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with tmp_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
        tmp_file.replace(state_file)
    except Exception as exc:
        log.error("`state` Error saving manifest: %s", exc)


def _empty_manifest(music_path: Path) -> Manifest:
    return Manifest(version=1, music_root=str(music_path), last_scan=0, last_server_audit=0, files={})


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
    parser.add_argument("--dry-run", action="store_true", help="Build the sync plan without changing the server or state.")
    parser.add_argument("--audit-server", action="store_true", help="Compare local state with /list_tracks/ during this run.")
    parser.add_argument("--no-delete", action="store_true", help="Do not delete stale server tracks during this run.")
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
        return "0.3.3"


def main() -> int:
    args, _unknown_args = _parse_args()
    _init_config(args.config_file)
    _init_logs()

    killer = GracefulKiller(kill_targets=[schedule.clear])
    log.info("`startup` Starting %s", APP_NAME)
    schedule.every().day.at(settings.music.scan_time).do(scan_music_directory, killer)

    if not args.dont_scan_now:
        scan_music_directory(
            killer,
            force=args.force_rescan,
            dry_run=args.dry_run,
            audit_server=args.audit_server,
            delete_missing=not args.no_delete,
        )

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
