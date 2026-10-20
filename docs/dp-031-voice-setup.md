# DP-031: First-Run Voice Setup

Implemented for the native source app on 2026-10-19. This adds no installer, Windows autostart registration, Spotify API requirement, or new automation commands.

## User Flow

1. Start the source app. Until setup is saved, **Voice setup** opens automatically. Existing profiles without the new completion flag also see it once.
2. Choose **System default microphone** or a named input. **Refresh** discovers connected inputs.
3. Click **Test microphone · 3 seconds** and speak. The input meter shows a local signal measurement; success means audio was detected, not that speech was recognized. Silence or capture failures leave saving disabled and show retry guidance.
4. Click **Prepare voice models**. The two stages prepare Hey Jarvis and local English transcription. Missing files download; cached files are reused. Failure leaves setup incomplete and permits retry.
5. Choose local operation with the checkbox, or leave it unchecked to preserve existing provider settings. Existing explicit cloud preferences are not changed automatically.
6. Click **Save setup**, then **Start wake word listening** in the tray. Say **Hey Jarvis**, wait for the cue, then **open calculator** or **what time is it**.

Reopen setup from the tray to change microphones. It pauses listening and refuses to overlap a native command. Saving does not resume listening automatically. **Later** or **Cancel setup** saves nothing. The dialog remains responsive during preparation; an in-flight library download may finish in the background after cancellation. Listening remains disabled until that job finishes. Model caches may remain after cancellation and be reused on retry.

## Persistence And Compatibility

- `microphone_device`: `null` for default, otherwise `{name, hostapi}`. Resolving the current index avoids selecting a different device after index changes. Missing or ambiguous saved devices report an error.
- `voice_setup_completed`: defaults to false for existing settings and is saved as true only after the microphone and models pass.
- Settings schema remains version 1 with backward-compatible optional fields.
- Save preserves aliases, recording duration, startup preference, default music app, and unknown fields. Selecting local mode changes both transcription and interpretation providers to `local`; unchecked keeps their existing values.
- Invalid JSON, unsupported settings versions, and failed replacements do not overwrite the existing file.
- No new dependency is needed; the UI uses existing PySide6 and audio/model libraries.
- Only native wake-word and command capture use the saved input. Development API microphone capture keeps its existing default-device behavior.

## Automated Verification

Final local verification on 2026-10-19: **463 tests passed** (36 added since DP-030), `compileall src tests` passed, `pip check` reported no broken requirements, and `git diff --check` passed. The suite retains one third-party Starlette/AnyIO deprecation warning.

The tests use fake input streams/models and temporary settings. They do not download models, record the laptop microphone, use cloud APIs, or execute desktop commands.

Coverage includes device filtering and stable selection, disconnected/ambiguous inputs, shared selection in both native streams, silence and cancellation, stream cleanup, model reuse/reset, failed downloads and retry, preserved settings, invalid JSON, failed atomic writes, old profiles, and actual Qt dialog/tray wiring.

The UI tests run offscreen, exercise its background jobs and save gating, and verify that saving alone does not start listening. A rendered dialog was inspected for readable content and accessible bottom controls.

## Manual Acceptance Checklist

On 2026-10-19, the owner confirmed that the requested source-app walkthrough worked: selecting/testing the microphone, preparing models, saving setup, enabling listening from the tray, and **Hey Jarvis → open calculator**. This confirms the main first-run flow on that laptop; it does not establish whether model files were freshly downloaded or already cached.

Source launch command for future regression checks:

```powershell
Set-Location C:\Users\manue\deskpilot
.\.venv\Scripts\python.exe -m deskpilot_backend.desktop
```

Quit older DeskPilot instances first. Do not use the old executable in `dist/`.

- [x] Open Voice setup and complete the main first-run walkthrough.
- [x] Select the intended microphone and successfully test while speaking.
- [ ] Closing with **Later** keeps listening off and permits reopening from the tray.
- [ ] Test while silent: saving remains unavailable until a successful retry.
- [x] Prepare voice models successfully.
- [ ] Exercise failed preparation and retry on real hardware; verify UI responsiveness during a fresh download.
- [x] Save and start listening from the tray. **Hey Jarvis → open calculator** works with the selected microphone.
- [ ] Quit/relaunch: saved setup is retained and the dialog does not reopen automatically.
- [ ] Reopen setup, select another input if available, retest/save, and confirm wake word and command capture both use it.
- [ ] Recheck DP-030 play, pause, next, previous, mute, and volume after completing setup.

Fresh downloads, disconnected hardware, and packaged execution still need real Windows validation. Stage progress is intentionally indeterminate within each download; it does not claim a byte percentage or remaining time.
