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
