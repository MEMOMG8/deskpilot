import io
from pathlib import Path

import pytest

from deskpilot_backend.model_cache import WAKE_ASSETS, ensure_wake_models, wake_cache_directory


def response(data=b"test-model", length=None):
    stream = io.BytesIO(data)
    stream.headers = {"Content-Length": str(len(data) if length is None else length)}
    return stream


def test_cache_is_per_user_not_install_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert wake_cache_directory() == tmp_path / "DeskPilot/models/openwakeword"


def test_missing_models_are_downloaded_atomically_and_reused(tmp_path):
    calls = []
    def download(url, *, timeout):
        calls.append((url, timeout))
        return response()
    directory = tmp_path / "models"
    assert ensure_wake_models(directory=directory, opener=download) == directory
    ensure_wake_models(directory=directory, opener=lambda *a, **kw: pytest.fail("already cached"))
    assert {url for url, _ in calls} == set(WAKE_ASSETS.values())
    assert all(timeout == 30 for _, timeout in calls)
    assert {p.name for p in directory.iterdir()} == set(WAKE_ASSETS)
    assert all(p.read_bytes() == b"test-model" for p in directory.iterdir())


def test_incomplete_download_never_becomes_cached_model_and_retry_works(tmp_path):
    with pytest.raises(OSError, match="Incomplete"):
        ensure_wake_models(directory=tmp_path, opener=lambda *a, **kw: response(b"short", 99))
    assert not list(tmp_path.iterdir())
    ensure_wake_models(directory=tmp_path, opener=lambda *a, **kw: response())
    assert len(list(tmp_path.iterdir())) == 3


def test_connection_failure_preserves_existing_assets(tmp_path):
    first = tmp_path / next(iter(WAKE_ASSETS))
    first.write_bytes(b"existing")
    def offline(*args, **kwargs):
        raise OSError("offline")
    with pytest.raises(OSError, match="offline"):
        ensure_wake_models(directory=tmp_path, opener=offline)
    assert first.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [first]
