"""Opt-in Windows install/update/uninstall check with a separate product identity.

Uses only a fresh build/installer-validation-* directory and its own HKCU
uninstall entry/Start menu shortcut. Never installs the production AppId.
Keeps logs and test data for inspection; does not capture audio or control media.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_installer", ROOT / "scripts/build-installer.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
VALIDATION_ID = "DeskPilot.InstallerValidation"
REG_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{VALIDATION_ID}_is1"


def registration():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return {
                name: winreg.QueryValueEx(key, name)[0]
                for name in ("InstallLocation", "DisplayVersion", "UninstallString")
            }
    except FileNotFoundError:
        return None


def run_setup(executable, log, *, install_dir=None, blocked=False):
    args = [str(executable), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/LOG={log}"]
    if install_dir is not None:
        args.append(f"/DIR={install_dir}")
    result = subprocess.run(args, cwd=log.parent, timeout=180, check=False)
    if blocked:
        if result.returncode == 0:
            raise AssertionError("Installer must fail when the application mutex is held")
    elif result.returncode != 0:
        raise AssertionError(f"Installer exit {result.returncode}; see {log}")


def main():
    if sys.platform != "win32":
        raise SystemExit("This integration check requires Windows.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-id", required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,70}", args.build_id):
        parser.error("Invalid build ID")
    package = ROOT / "dist" / args.build_id / "DeskPilot"
    builder.validate_payload(package)
    if registration() is not None:
        raise RuntimeError("An installer-validation product already exists. Inspect/uninstall it first.")

    from win32com.client import Dispatch
    from win32com.shell import shell, shellcon
    from deskpilot_backend.installation_guard import WindowsMutex

    shortcut = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, 0, 0)) / "DeskPilot Installer Validation.lnk"
    if shortcut.exists():
        raise RuntimeError("Validation shortcut already exists; refusing to overwrite it.")
    run_dir = (ROOT / "build" / f"installer-validation-{uuid.uuid4().hex[:12]}").resolve()
    assert run_dir.is_relative_to((ROOT / "build").resolve())
    run_dir.mkdir()
    install_dir = run_dir / "installed"
    compiler = ROOT / "build/tools/inno-6.7.3/ISCC.exe"
    before = builder.compile_installer(package, run_dir / "before", compiler, "validation-before", validation=True)
    after = builder.compile_installer(package, run_dir / "after", compiler, "validation-after", validation=True, version="0.1.1")
    report = {"ok": False, "checks": {}, "production_app_touched": False}
    checks = report["checks"]
    report_path = run_dir / "lifecycle.json"
    # Realistic fixtures live outside the installation tree, as in production.
    profile = run_dir / "profile"
    data = profile / "Documents/DeskPilot"
    data.mkdir(parents=True)
    fixtures = {
        data / "settings.json": '{"version":1,"voice_setup_completed":true,"wake_listening_on_startup":false,"command_capture_duration_seconds":5}',
        data / "notes/keep.txt": "My note must survive an update and uninstall.",
        # Use the app's own serialization: startup re-saves pending reminders.
        data / "reminders.json": json.dumps([{
            "id": "preserve-me", "text": "Keep my reminder",
            "due_at": "2099-01-01T00:00:00+00:00",
        }], indent=2),
        profile / "AppData/Local/DeskPilot/models/keep.bin": "cached model sentinel",
    }
    for path, content in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    baseline = {path: path.read_bytes() for path in fixtures}

    def preserved():
        assert all(path.is_file() and path.read_bytes() == content for path, content in baseline.items())

    def check_install(version, build_id):
        reg = registration()
        assert reg is not None and reg["DisplayVersion"] == version
        assert Path(reg["InstallLocation"]).resolve() == install_dir.resolve()
        target = install_dir / "versions" / build_id
        expected = json.loads((package.parent / "files-sha256.json").read_text())
        actual = {
            path.relative_to(target).as_posix(): builder.package_windows.sha256(path)
            for path in target.rglob("*") if path.is_file()
        }
        assert actual == expected, "Installed payload differs from the verified bundle"
        link = Dispatch("WScript.Shell").CreateShortcut(str(shortcut))
        assert Path(link.TargetPath).resolve() == target / "DeskPilot.exe"
        assert Path(link.WorkingDirectory).resolve() == target
        preserved()
        return target

    try:
        mutex = WindowsMutex()
        handle = mutex.create(r"Local\DeskPilot.InstallerValidation.Running")
        try:
            run_setup(before, run_dir / "blocked-install.log", install_dir=install_dir, blocked=True)
            assert registration() is None and not install_dir.exists()
        finally:
            mutex.close(handle)
        checks["running_app_blocks_install"] = True
        run_setup(before, run_dir / "install.log", install_dir=install_dir)
        check_install("0.1.0", "validation-before")
        checks["per_user_install_shortcut_hashes"] = True
        # An untracked file must not be removed on update or uninstall.
        unrelated = install_dir / "user-kept.txt"
        unrelated.write_text("keep this file", encoding="utf-8")
        run_setup(after, run_dir / "update.log")
        target = check_install("0.1.1", "validation-after")
        checks["update_reuses_location_preserves_data"] = True
        builder.package_windows.smoke_test(target, run_dir / "installed-self-test.json")
        checks["installed_executable_self_test"] = True

        # Launch the installed normal entrypoint with existing settings. Verify
        # it keeps those preferences; no listening, recording or cloud keys.
        env = {k: v for k, v in os.environ.items() if not k.startswith(
            ("PYTHON", "QT_", "QML", "HF_", "HUGGINGFACE", "OPENAI", "SPOTIFY")
        ) and k != "VIRTUAL_ENV"}
        system = Path(os.environ["SystemRoot"])
        env.update(
            USERPROFILE=str(profile), HOME=str(profile),
            LOCALAPPDATA=str(profile / "AppData/Local"), APPDATA=str(profile / "AppData/Roaming"),
            HF_HOME=str(profile / "huggingface"), PATH=f"{system / 'System32'};{system}",
            QT_QPA_PLATFORM="offscreen",
        )
        process = subprocess.Popen([str(target / "DeskPilot.exe")], cwd=run_dir, env=env)
        try:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                preserved()
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
                kernel.OpenMutexW.restype = wintypes.HANDLE
                marker = kernel.OpenMutexW(0x00100000, False, r"Local\DeskPilot.Desktop.Running")
                assert marker, "Installed executable did not publish its installer lifetime marker"
                mutex.close(marker)
            else:
                raise AssertionError(f"Installed app exited early: {process.returncode}")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        checks["existing_settings_launch_and_runtime_marker"] = True

        uninstaller = install_dir / "unins000.exe"
        # Verify the target belongs to this isolated test before executing removal.
        assert install_dir.resolve().is_relative_to(run_dir)
        assert registration()["UninstallString"].strip('"') == str(uninstaller)
        handle = mutex.create(r"Local\DeskPilot.InstallerValidation.Running")
        try:
            run_setup(uninstaller, run_dir / "blocked-uninstall.log", blocked=True)
            assert uninstaller.exists() and registration() is not None
        finally:
            mutex.close(handle)
        checks["running_app_blocks_uninstall"] = True
        run_setup(uninstaller, run_dir / "uninstall.log")
        assert registration() is None and not shortcut.exists()
        assert not list(install_dir.rglob("DeskPilot.exe"))
        assert not (install_dir / "versions").exists()
        assert unrelated.read_text(encoding="utf-8") == "keep this file"
        preserved()
        checks["uninstall_removes_app_keeps_user_files"] = True
        run_setup(after, run_dir / "reinstall.log", install_dir=install_dir)
        check_install("0.1.1", "validation-after")
        checks["reinstall_keeps_data"] = True
        run_setup(uninstaller, run_dir / "final-uninstall.log")
        assert registration() is None and not shortcut.exists()
        preserved()
        report["ok"] = True
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Lifecycle report: {report_path}", flush=True)
        # On failure leave the test registration/files for diagnosis. Do not
        # guess at cleanup or touch any other DeskPilot installation.
    print("Installer lifecycle checks passed.")


if __name__ == "__main__":
    main()
