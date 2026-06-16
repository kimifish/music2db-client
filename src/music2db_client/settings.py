from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "music2db-client"
    logging_config: Path | None = None


class MusicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    scan_time: str = "04:00"
    extensions: list[str] = Field(default_factory=lambda: [".mp3", ".flac", ".m4a", ".ogg"])


class MusicDbSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://localhost"
    port: int = 5005
    one_track_endpoint: str = "/add_track/"
    many_tracks_endpoint: str = "/add_tracks/"
    delete_track_endpoint: str = "/delete_track/"
    list_tracks_endpoint: str = "/list_tracks/"
    timeout_seconds: float = 30
    retry_count: int = 3
    retry_backoff_seconds: float = 2

    @property
    def base_url(self) -> str:
        return f"{self.url.rstrip('/')}:{self.port}"


class ScanSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = 100


class SyncSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_interval_hours: float = 24
    delete_missing: bool = True
    dry_run: bool = False


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppSettings = Field(default_factory=AppSettings)
    music: MusicSettings
    music_db: MusicDbSettings = Field(default_factory=MusicDbSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    logging: dict[str, Any] = Field(default_factory=dict)
