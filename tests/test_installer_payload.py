import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "build_installer", Path(__file__).resolve().parents[1] / "scripts/build-installer.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def payload(tmp_path, monkeypatch):
    package = tmp_path / "DeskPilot"
    package.mkdir()
    (package / "DeskPilot.exe").write_bytes(b"fake executable")
    (package / "build-info.json").write_text(json.dumps({
        "packaged_self_test_passed": True, "source_sha256": "current",
    }))
    (tmp_path / "self-test.json").write_text(json.dumps({
        "ok": True, "frozen": True, "checks": {"startup": {"ok": True}},
    }))
    (tmp_path / "files-sha256.json").write_text(json.dumps({
        path.name: installer.package_windows.sha256(path) for path in package.iterdir()
    }))
    monkeypatch.setattr(installer.package_windows, "source_fingerprint", lambda: "current")
    return package


def test_validated_payload_is_accepted(payload):
    assert installer.validate_payload(payload)["source_sha256"] == "current"


@pytest.mark.parametrize("change", ["edited", "missing", "extra"])
def test_payload_changed_since_smoke_test_is_rejected(payload, change):
    if change == "edited":
        (payload / "DeskPilot.exe").write_bytes(b"changed")
    elif change == "missing":
        (payload / "DeskPilot.exe").unlink()
    else:
        (payload / "extra.dll").write_bytes(b"extra")
    with pytest.raises(ValueError, match="inventory or SHA-256"):
        installer.validate_payload(payload)


def test_stale_source_payload_is_rejected(payload, monkeypatch):
    monkeypatch.setattr(installer.package_windows, "source_fingerprint", lambda: "new")
    with pytest.raises(ValueError, match="stale"):
        installer.validate_payload(payload)


def test_failed_packaged_check_cannot_be_wrapped(payload):
    report = payload.parent / "self-test.json"
    report.write_text(json.dumps({"ok": True, "frozen": True, "checks": {"qt": {"ok": False}}}))
    with pytest.raises(ValueError, match="failed self-test"):
        installer.validate_payload(payload)


@pytest.mark.parametrize("build_id", ["../outside", "abc/def", 'abc"def', ""])
def test_unsafe_build_id_cannot_reach_compiler(tmp_path, build_id):
    with pytest.raises(ValueError, match="build ID"):
        installer.compile_installer(tmp_path, tmp_path / "output", Path("unused"), build_id)
    assert not (tmp_path / "output").exists()
