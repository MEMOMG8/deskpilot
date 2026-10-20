# DP-033: Per-User Windows Test Installer

Scope: install, update and uninstall the validated desktop application. This is
an unsigned test installer, not a public release or automatic updater.

## Behavior

- Installs for the current user at `%LOCALAPPDATA%\Programs\DeskPilot`, with
  `PrivilegesRequired=lowest`. No administrator prompt or machine registration.
- Adds **DeskPilot** to the user's Start menu and Windows' installed-apps list.
- Targets Windows x64, Windows 10 1809 or newer; ARM64 is not a validated target.
- Uses the stable `DeskPilot.Desktop` AppId across updates.
- Keeps each build's runtime in `versions/<BuildId>`. An update points the Start
  menu shortcut to the new build, avoiding mixed old/new Python modules or DLLs.
  Older managed runtimes remain on disk until uninstall; this is a deliberate
  test-stage tradeoff, not an automatic rollback feature.
- Installed/packaged applications hold a Windows named mutex for their lifetime.
  Setup and uninstall ask the user to quit DeskPilot before proceeding. They do
  not force termination or restart the application. Old DP-032 builds and direct
  `python -m deskpilot_backend.desktop` launches lack this marker: close them
  manually before installing.
- Installation does not run the app, activate listening, or register autostart.
- Uninstall removes all Inno-managed versions, the shortcut and uninstall entry.
  It does not recursively wipe the installation directory or remove unrelated
  files the user placed there.
- Settings, notes and reminders under `~/Documents/DeskPilot`, the wake-model
  cache under `%LOCALAPPDATA%\DeskPilot`, and the Hugging Face cache survive
  updates and uninstall. Reinstall can reuse them.

## Build

Prepare the project `.venv` as in [Windows build](windows-build.md), then run:

```powershell
.\scripts\build-installer.ps1 -BuildId dp033-test-20261020-r2
```

The wrapper obtains Inno Setup **6.7.3** from the upstream GitHub release into
ignored `build/tools`, verifies the pinned SHA-256 and Authenticode publisher
before execution, and uses its `/PORTABLE=1` mode. It does not install a global
compiler, add PATH entries or associate `.iss` files. Reused build labels are
rejected. The recipient needs neither Inno Setup nor Python.

It then creates and smoke-tests a fresh PyInstaller payload. The installer step
audits that payload and requires an exact SHA-256 inventory and current source
fingerprint. It rejects stale DP-032 payloads and modified/extra/missing files.
The executable, checksum, compiler log and provenance are written to:

```text
dist/<BuildId>/installer/DeskPilot-0.1.0-<BuildId>-setup.exe
dist/<BuildId>/installer/SHA256SUMS.txt
dist/<BuildId>/installer/installer-info.json
```

To compile only the installer immediately after a verified payload build:

```powershell
.\.venv\Scripts\python.exe -B scripts/build-installer.py --build-id dp033-test-20261020-r2
```

Do not change source/build scripts between those steps; the fingerprint is
checked. No signing credentials are embedded. Public release still needs the
project/dependency/model redistribution review and signing decision. Inno's
commercial licensing terms should be reviewed if DeskPilot is used commercially.

## Automated Lifecycle Validation

```powershell
.\.venv\Scripts\python.exe -B scripts/test-installer.py --build-id dp033-test-20261020-r2
```

This opt-in integration check compiles the same recipe with a separate
`DeskPilot.InstallerValidation` AppId, name and mutex. It installs under a unique
`build/installer-validation-*` directory, creates its own HKCU registration and
Start menu link, and removes them on success. It refuses to overwrite a previous
validation installation. Logs and synthetic data remain for inspection.

It checks:

1. An application lifetime marker blocks install and uninstall.
2. Per-user registration, exact installed file hashes and shortcut target.
3. A simulated `0.1.0` to `0.1.1` update using the same application binary,
   a different runtime directory, and the same AppId without passing `/DIR` again.
4. Installed executable self-test and normal startup with saved preferences,
   no microphone capture or cloud credentials.
5. Uninstall removes both managed runtime versions and its registration/link.
6. Synthetic settings, notes, a future reminder, model-cache sentinel and an
   unrelated file inside the installation directory survive.
7. Reinstall preserves the same data; final uninstall cleans up registration.

This tests the installer mechanics. It does not claim a future application
version's data migrations or interactive Windows security dialogs are validated.

The first lifecycle run passed install/update and the installed self-test, then
correctly exposed a fixture mismatch: application startup rewrites pending
reminders with its canonical JSON formatting. The reminder's content was intact.
The fixture now uses the app's serialization, retaining byte-for-byte preservation
checks. That isolated validation installation was uninstalled; its logs remain
under `build/installer-validation-85036c7daa6e`.

## Manual Acceptance

On the second laptop:

1. Quit any portable/source DeskPilot instance from its tray.
2. Run the new `*-setup.exe` as a standard user. Confirm it does not ask for
   administrator credentials and that **DeskPilot** appears in Start.
3. Launch from Start, complete/reopen Voice setup, and test wake word, Spotify
   play/pause/previous/next, mute and volume.
4. Quit DeskPilot. Run the same installer again and launch from Start. Check that
   microphone preferences, notes and reminders remain. This is a reinstall;
   a true later-version update is covered separately by the simulated harness.
5. Leave DeskPilot running and try uninstalling: it should ask you to close it.
   Quit from the tray, then uninstall through Windows Settings > Apps.
6. Confirm the Start menu entry disappears and personal data remains.
7. Reinstall and check that saved settings and models can be reused.

The earlier DP-032 ZIP was reported working on the maintainer's laptop and a
second laptop. Whether Python was absent on the second laptop was not specified.
DP-033 adds a new executable lifetime marker and installation layer, so it needs
this manual acceptance in addition to the prior ZIP test.

## Build Record — 2026-10-20

- Source suite: **488 passed**, with the existing Starlette/AnyIO deprecation
  warning. `compileall` passed for source, tests and scripts; dependency,
  PowerShell syntax and whitespace checks passed.
- Initial pytest invocation encountered access restrictions in its shared
  temporary directory. The full suite passed with a new isolated profile and
  temporary directory; no product change was needed.
- Final build: **dp033-test-20261020-r2**. All seven frozen application checks
  passed. The portable ZIP passed integrity verification.
- Installer: **159,510,957 bytes**, about 152 MiB. Its embedded execution
  manifest is `asInvoker`. Validation was launched from a non-elevated process.
- All **eight lifecycle checks passed**, including the installed executable's
  self-test, simulated update, active-app guards, data preservation, uninstall
  and reinstall. Report: `build/installer-validation-1b5993566aad/lifecycle.json`.
  The final validation uninstall entry and Start menu shortcut were removed.
  The production DeskPilot installation was not changed by this harness.
- Installer SHA-256:

```text
fa7761f2235215a150694be47e0ad5423f3b2e218f785353c8a79b4d6678529c
```

Artifact:

```text
dist/dp033-test-20261020-r2/installer/DeskPilot-0.1.0-dp033-test-20261020-r2-setup.exe
```

Build metadata records the pre-checkpoint Git HEAD and dirty state together with
the exact source/build fingerprint. The generated binaries and logs are ignored
by Git; committing the source does not publish an installer or a release.

## References

- [Inno downloads and verification](https://jrsoftware.org/isdl.php)
- [Per-user installation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)
- [Application lifetime mutex](https://jrsoftware.org/ishelp/topic_setup_appmutex.htm)
- [Uninstall deletion guidance](https://jrsoftware.org/ishelp/topic_uninstalldeletesection.htm)
