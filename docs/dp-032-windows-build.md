# DP-032: Windows Test Distribution

Work date: 2026-10-20. Scope: build the current DP-030/DP-031 source as an independently runnable Windows x64 test distribution. No installer, autostart registration, public release, or signing is added.

## Packaging Changes

- The tracked PyInstaller recipe includes Qt setup, native audio/TTS libraries, WinRT namespace packages, and the desktop command code.
- Build-time PATH is isolated and binary origins are checked against Python/Windows locations. This prevents collecting incompatible DLLs from other installed developer tools.
- Builds use unique `dist/<BuildId>` and `build/<BuildId>` directories. Existing artifacts are preserved.
- The executable has a Windows test-version resource and handles absent console streams safely.
- Wake models live in a writable per-user cache and use explicit paths. Only the three required ONNX assets download, from fixed upstream URLs; partial transfers are discarded.
- Model weights, developer caches, settings, tokens, and recordings are excluded from the test package. The package is audited before ZIP creation.
- A packaged `--self-test REPORT_JSON` mode checks dependencies and initializes the setup window without microphone capture, TTS speech, model downloads, or automation.
- Packaging produces a complete folder, verified ZIP, build provenance, file hashes, and a ZIP checksum.

## Verification

Source suite: **475 tests passed**, with the existing Starlette/AnyIO deprecation warning. Compile checks over source, tests, and scripts passed. Dependency and Git whitespace checks passed.

Build **dp032-test-20261020-r2** completed successfully. All seven packaged checks passed: bundled imports, Qt setup using the Windows platform plugin, audio-device enumeration, SAPI voices, read-only Windows media sessions, CPU inference engines, and ordinary desktop startup with fresh settings. No microphone recording or automation was performed by these checks.

Artifacts (ignored by Git):

```text
dist/dp032-test-20261020-r2/DeskPilot/DeskPilot.exe
dist/dp032-test-20261020-r2/DeskPilot-0.1.0-dp032-test-20261020-r2-windows-x64.zip
dist/dp032-test-20261020-r2/self-test.json
dist/dp032-test-20261020-r2/files-sha256.json
dist/dp032-test-20261020-r2/SHA256SUMS.txt
```

ZIP size: **182,421,921 bytes** (about 174 MiB). SHA-256:

```text
ced376b3ba66a2cde808bfcfab534df4fa62c67de3d04c1a7f0d1dd748bdcac0
```

The ZIP was read back for integrity verification. `build-info.json` records the pre-commit Git HEAD, dirty working-tree state, and a fingerprint of the exact source/build inputs used. The subsequent checkpoint commit does not change the executable's recorded provenance.

The first attempt was rejected before ZIP creation: its audit found dependency bytecode, and its smoke test found a Qt load failure caused by an unrelated ICU DLL collected from the developer PATH. The recipe now filters expanded metadata caches/local-install metadata and isolates DLL discovery. The failed attempt is retained only as a diagnostic artifact; it is not the test distribution to use.

A fresh wake-model download into a temporary user cache and inference on a synthetic silent frame succeeded. This exercised the new cache path without microphone recording or reuse of the developer's cached models.

The packaged self-test uses temporary profile/cache directories, a working directory outside the repository, a minimal Windows PATH, and no OpenAI/Spotify credentials. Success establishes that those startup checks work on the build laptop; it is not proof of clean-machine compatibility.

## Manual Handoff

Follow-up: the maintainer reported successful functional testing on the build
laptop and on a second laptop before DP-033 began. The second machine's Windows
version and whether Python was installed were not specified.

1. Quit any running source or old-build DeskPilot instance.
2. Extract the new ZIP completely. Keep `_internal` next to `DeskPilot.exe`.
3. Launch the executable from the extracted folder.
4. Open Voice setup from the tray if this laptop already has saved settings. Test the microphone, prepare models, save, and start listening.
5. Test **Hey Jarvis → open calculator**, then Spotify open/play/pause/next/previous/mute/volume.
6. Quit/relaunch and check saved preferences and model cache reuse.
7. Repeat on a clean Windows x64 machine without Python/repository access before preparing an installer.

The package is unsigned and intended for testing. Existing laptop settings are shared with the source app; they are not embedded in the ZIP. Public distribution still needs the clean-machine checklist and a review of bundled dependency/model redistribution terms.
