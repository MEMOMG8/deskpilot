"""Audit, smoke-test and archive an already-built Windows distribution."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def audit(package):
    forbidden = []
    for path in package.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(package)
        if (
            path.name.lower() in {"settings.json", "reminders.json", "spotify.bin"}
            or path.name.lower().startswith(".env")
            or path.suffix.lower() in {".onnx", ".tflite", ".wav", ".mp3"}
            or any(part in {".git", ".venv", "__pycache__"} for part in relative.parts)
        ):
            forbidden.append(str(relative))
    if forbidden:
        raise RuntimeError(f"Unexpected user data, model weights or build caches: {forbidden}")


def source_fingerprint():
    paths = sorted(
        path for base in ("src", "scripts", "packaging")
        for path in (ROOT / base).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ) + [ROOT / "pyproject.toml"]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def smoke_test(package):
    report = package.parent / "self-test.json"
    with tempfile.TemporaryDirectory(prefix="deskpilot-frozen-check-") as directory:
        env = os.environ.copy()
        for name in list(env):
            if (
                name.startswith(("PYTHON", "QT_", "QML", "HF_", "HUGGINGFACE", "OPENAI", "SPOTIFY"))
                or name == "VIRTUAL_ENV"
            ):
                env.pop(name)
        system = Path(os.environ["SystemRoot"])
        env.update(
            PATH=f"{system / 'System32'};{system}",
            USERPROFILE=directory, HOME=directory,
            APPDATA=directory, LOCALAPPDATA=directory,
            HF_HOME=str(Path(directory) / "huggingface"),
        )
        process = subprocess.run(
            [str(package / "DeskPilot.exe"), "--self-test", str(report)],
            cwd=directory, env=env, timeout=90, check=False,
        )
        if process.returncode != 0 or not report.exists():
            raise RuntimeError(f"Packaged smoke check failed ({process.returncode}). See {report}")
        result = json.loads(report.read_text(encoding="utf-8"))
        if not result.get("ok") or not result.get("frozen"):
            raise RuntimeError(f"Packaged checks did not pass: {report}")
        # Exercise the ordinary entrypoint too, with a fresh profile and no
        # visible window or microphone activation, then stop only this test process.
        startup = subprocess.Popen(
            [str(package / "DeskPilot.exe")], cwd=directory,
            env={**env, "QT_QPA_PLATFORM": "offscreen"},
        )
        try:
            try:
                startup.wait(timeout=10)
            except subprocess.TimeoutExpired:
                settings = Path(directory) / "Documents/DeskPilot/settings.json"
                if not settings.exists():
                    raise RuntimeError("Desktop startup did not create its fresh settings")
                if json.loads(settings.read_text())["voice_setup_completed"]:
                    raise RuntimeError("Fresh startup unexpectedly completed voice setup")
            else:
                raise RuntimeError(f"Desktop exited during startup: {startup.returncode}")
        finally:
            if startup.poll() is None:
                startup.terminate()
                try:
                    startup.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    startup.kill()
                    startup.wait(timeout=5)
        result["checks"]["desktop_startup"] = {
            "ok": True, "details": "Ordinary entrypoint stayed running with a fresh profile; no listening enabled."
        }
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--build-id", required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    if not package.is_relative_to(ROOT / "dist"):
        raise ValueError("Package must be inside this repository's dist directory")
    audit(package)
    checks = smoke_test(package)
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    info = {
        "build_id": args.build_id, "version": "0.1.0-test",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_commit, "working_tree_dirty": dirty,
        "source_sha256": source_fingerprint(),
        "python": platform.python_version(), "architecture": platform.machine(),
        "packaged_self_test_passed": checks["ok"],
        "dependencies": dict(sorted(
            (distribution.metadata["Name"], distribution.version)
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        )),
    }
    (package / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    (package / "README.txt").write_text(
        "DeskPilot v0.1 TEST BUILD (unsigned)\n\n"
        "Extract the ENTIRE DeskPilot folder, then run DeskPilot.exe. Keep _internal beside it.\n"
        "Python is not required. Do not run the executable inside the ZIP.\n"
        "First run: select/test microphone, prepare models (internet for missing files), save,\n"
        "then choose Start wake word listening in the tray. Say Hey Jarvis, wait for the cue,\n"
        "then say open calculator. Use Stop wake word listening or Quit DeskPilot to stop.\n\n"
        "Spotify Desktop must be installed separately. No Spotify Developer account or OAuth\n"
        "is required for open spotify, play music, pause music, next track, previous track.\n"
        "A first media session may require starting a song once in Spotify.\n\n"
        "Settings/notes/reminders: ~/Documents/DeskPilot. Wake models: %LOCALAPPDATA%/DeskPilot/models.\n"
        "Local transcription uses the Hugging Face user cache. No personal data/models are bundled.\n"
        "This is a local test artifact, not an installer or an approved public release.\n",
        encoding="utf-8",
    )
    files = {
        path.relative_to(package).as_posix(): sha256(path)
        for path in sorted(package.rglob("*")) if path.is_file()
    }
    (package.parent / "files-sha256.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")
    archive = package.parent / f"DeskPilot-0.1.0-{args.build_id}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(package.parent))
    with zipfile.ZipFile(archive) as output:
        bad = output.testzip()
        if bad:
            raise RuntimeError(f"Archive verification failed: {bad}")
    (package.parent / "SHA256SUMS.txt").write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii")
    print(f"Packaged checks passed. ZIP: {archive}")
    print(f"ZIP bytes: {archive.stat().st_size}; SHA256: {sha256(archive)}")


if __name__ == "__main__":
    main()
