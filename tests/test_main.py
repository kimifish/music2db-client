from types import SimpleNamespace

from music2db_client import main
from music2db_client.settings import MusicDbSettings, MusicSettings, Settings


def test_sanitize_metadata_keeps_only_json_primitives():
    cleaned = main.sanitize_metadata(
        {
            "artist": "Artist",
            "length": 123,
            "rating": 4.5,
            "favorite": True,
            "missing": None,
            "custom": object(),
        }
    )
    assert cleaned["artist"] == "Artist"
    assert cleaned["length"] == 123
    assert cleaned["rating"] == 4.5
    assert cleaned["favorite"] is True
    assert "missing" not in cleaned
    assert isinstance(cleaned["custom"], str)


def test_health_requires_chromadb_and_embeddings_ok(monkeypatch, tmp_path):
    main.settings = Settings(music=MusicSettings(path=tmp_path), music_db=MusicDbSettings(url="http://server", port=5005))

    class Response:
        status_code = 200

        def json(self):
            return {"status": "Server is running", "chromadb": "ok", "embeddings": "error"}

    monkeypatch.setattr(main.requests, "get", lambda url, timeout: Response())

    assert main.check_server_health() is False


def test_health_accepts_contract_response(monkeypatch, tmp_path):
    main.settings = Settings(music=MusicSettings(path=tmp_path), music_db=MusicDbSettings(url="http://server", port=5005))

    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "status": "Server is running",
            "chromadb": "ok",
            "embeddings": "ok",
            "embedding_model": "intfloat/multilingual-e5-small",
        },
    )
    monkeypatch.setattr(main.requests, "get", lambda url, timeout: response)

    assert main.check_server_health() is True


def test_build_sync_plan_sends_new_and_changed_and_deletes_missing(monkeypatch, tmp_path):
    main.settings = Settings(music=MusicSettings(path=tmp_path))
    unchanged = tmp_path / "unchanged.mp3"
    changed = tmp_path / "changed.mp3"
    new = tmp_path / "new.mp3"
    for path in (unchanged, changed, new):
        path.write_bytes(b"audio")

    def metadata(file_path):
        return {"title": file_path.stem}

    monkeypatch.setattr(main, "extract_metadata", metadata)
    manifest = main.Manifest(
        version=1,
        music_root=str(tmp_path),
        last_scan=1,
        last_server_audit=1,
        files={
            "unchanged.mp3": main.FileRecord(
                mtime=unchanged.stat().st_mtime,
                size=unchanged.stat().st_size,
                metadata_hash=main._metadata_hash({"title": "unchanged"}),
            ),
            "changed.mp3": main.FileRecord(mtime=0, size=0, metadata_hash="old"),
            "deleted.mp3": main.FileRecord(mtime=1, size=1, metadata_hash="deleted"),
        },
    )

    plan = main._build_sync_plan(tmp_path, manifest, SimpleNamespace(kill_now=False))

    assert [track["file_path"] for track in plan.tracks_to_send] == ["changed.mp3", "new.mp3"]
    assert plan.paths_to_delete == ["deleted.mp3"]
    assert set(plan.manifest.files) == {"unchanged.mp3", "changed.mp3", "new.mp3"}


def test_delete_track_url_encodes_file_path(monkeypatch, tmp_path):
    main.settings = Settings(
        music=MusicSettings(path=tmp_path),
        music_db=MusicDbSettings(url="http://server", port=5005),
    )
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"deleted": True}

    def delete(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(main.requests, "delete", delete)

    assert main._delete_track("Artist/Album/Track 1.mp3") is True
    assert captured["url"] == "http://server:5005/delete_track/?file_path=Artist%2FAlbum%2FTrack%201.mp3"


def test_save_and_load_manifest_roundtrip(monkeypatch, tmp_path):
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    manifest = main.Manifest(
        version=1,
        music_root=str(tmp_path),
        last_scan=10,
        last_server_audit=5,
        files={"track.mp3": main.FileRecord(mtime=1.2, size=42, metadata_hash="abc")},
    )

    main._save_manifest(manifest)
    loaded = main._load_manifest(tmp_path)

    assert loaded.last_scan == 10
    assert loaded.last_server_audit == 5
    assert loaded.files["track.mp3"].metadata_hash == "abc"


def test_audit_respects_runtime_no_delete(monkeypatch, tmp_path):
    main.settings = Settings(music=MusicSettings(path=tmp_path))
    deleted = []
    plan = main.SyncPlan(
        tracks_to_send=[],
        paths_to_delete=[],
        manifest=main.Manifest(
            version=1,
            music_root=str(tmp_path),
            last_scan=0,
            last_server_audit=0,
            files={"local.mp3": main.FileRecord(mtime=1, size=1, metadata_hash="hash")},
        ),
        metadata_errors=0,
        files_seen=1,
    )

    monkeypatch.setattr(main, "_list_server_tracks", lambda: {"local.mp3", "stale.mp3"})
    monkeypatch.setattr(main, "_delete_tracks", lambda paths: deleted.extend(paths) or True)

    assert main._audit_server(plan, tmp_path, delete_missing=False) is True
    assert deleted == []
