import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "package_windows", Path(__file__).resolve().parents[1] / "scripts/package-windows.py"
)
package_windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_windows)


@pytest.mark.parametrize("relative", [
    "settings.json", "_internal/spotify.bin", ".env.local",
    "_internal/openwakeword/resources/models/hey_jarvis_v0.1.onnx",
    "_internal/.venv/private.txt", "recording.wav",
])
def test_package_audit_rejects_user_data_and_model_caches(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not for distribution")
    with pytest.raises(RuntimeError, match="Unexpected"):
        package_windows.audit(tmp_path)


def test_package_audit_accepts_runtime_libraries(tmp_path):
    (tmp_path / "DeskPilot.exe").write_bytes(b"test executable")
    runtime = tmp_path / "_internal"
    runtime.mkdir()
    (runtime / "python311.dll").write_bytes(b"test library")
    package_windows.audit(tmp_path)


def test_source_fingerprint_ignores_bytecode_but_changes_with_source(tmp_path, monkeypatch):
    for name in ("src", "scripts", "packaging"):
        (tmp_path / name).mkdir()
    (tmp_path / "pyproject.toml").write_text("version = 'test'")
    source = tmp_path / "src/app.py"
    source.write_text("first")
    monkeypatch.setattr(package_windows, "ROOT", tmp_path)
    original = package_windows.source_fingerprint()
    cache = tmp_path / "src/__pycache__"
    cache.mkdir()
    (cache / "app.pyc").write_bytes(b"bytecode")
    assert package_windows.source_fingerprint() == original
    source.write_text("second")
    assert package_windows.source_fingerprint() != original
