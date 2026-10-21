# Windows Build

This project can be packaged as a local Windows tray application with PyInstaller.

For the per-user Windows installer, use
[DP-033 build and validation](dp-033-installer.md). The portable ZIP remains
available for diagnosis and testing.

## Prerequisites

- Windows 10 or 11
- Python 3.11 or newer
- Project dependencies installed from the repository configuration:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

PyInstaller is a development/build dependency only. It is not required by DeskPilot at runtime.

The Windows-only project dependencies include `winrt-Windows.Foundation`, `winrt-Windows.Foundation.Collections`, and `winrt-Windows.Media.Control`. They provide asynchronous operations, session collection support, and the local media session API. Install them through the project environment; no global installation is needed. The build script collects the `winrt` namespace because the adapter imports it lazily.

## Source And Packaged Validation

DP-030 and DP-031 have been tested from source on the maintainer's laptop. DP-032 produces a new, separately named test artifact. The old `dist/DeskPilot/DeskPilot.exe` is retained and must not be used to validate these changes. A test build is not an installer or a verified public release.

To validate the current source from the repository root:

```powershell
.\.venv\Scripts\python.exe -m deskpilot_backend.desktop
```

See [DP-030 validation](dp-030-validation.md) for the tested cases and remaining checks.

## Build Command

From the repository root:

```powershell
.\scripts\build-windows.ps1
# Or choose a unique label:
.\scripts\build-windows.ps1 -BuildId my-next-test
```

The script uses the tracked `packaging/DeskPilot.spec` recipe to build a PyInstaller `--onedir`, `--noconsole` distribution named `DeskPilot`. It requires the repository `.venv`, checks dependencies, and refuses to overwrite an existing build label. The build uses a minimal PATH and rejects DLLs from outside Python/Windows, avoiding accidental dependencies on unrelated developer tools. No previous distribution is deleted. Build logs are written to `build/<BuildId>/pyinstaller.log`.

## Output

The executable is created at:

```text
dist/<BuildId>/DeskPilot/DeskPilot.exe
```

Run it from PowerShell or File Explorer:

```powershell
.\dist\dp032-test-20261020-r2\DeskPilot\DeskPilot.exe
```

Distribute the generated `DeskPilot-0.1.0-<BuildId>-windows-x64.zip`, not the executable alone. Extract the entire folder and preserve `_internal` beside the executable. The recipient does not need Python.

Each completed build includes `self-test.json`, a per-file SHA-256 inventory, ZIP checksum, and `DeskPilot/build-info.json` with build ID, source fingerprint, Git HEAD/dirty status, runtime version, and build-environment dependency versions. The ZIP is read back to verify its integrity.

The packaged self-test runs from a temporary working directory with temporary user/cache locations, no cloud credentials, and no Python in PATH. It checks bundled imports, the actual Qt setup window, audio-device enumeration, SAPI voice availability, read-only Windows media access, and CPU inference libraries. A separate offscreen startup check runs the ordinary desktop entrypoint with fresh settings and stops only that test process. Neither check records, speaks, downloads models, or sends media commands. They do not replace testing on a clean Windows machine.

DeskPilot starts in the Windows system tray. The executable carries a test version resource and is unsigned; Windows may show an unknown-publisher warning. This build is for controlled testing.

To enable optional OpenAI command transcription for the native tray app, set the environment variable before launching:

```powershell
$env:OPENAI_API_KEY = "your_api_key_here"
.\dist\dp032-test-20261020-r2\DeskPilot\DeskPilot.exe
```

Do not commit or print real API keys.

Public Spotify Desktop commands require the installed Spotify app and its `spotify:` protocol. `open spotify`, `play music`, `pause music`, next, and previous do not need OAuth, a Client ID, or a developer account. Windows must expose a current media session for playback controls; another active player can receive those commands.

### Experimental Spotify Web API

Only for testing the retained experimental API connector, create a Spotify Developer app with this exact redirect URI:

```text
http://127.0.0.1:8765/callback
```

Then set only the Client ID before launching:

```powershell
$env:SPOTIFY_CLIENT_ID = "your_spotify_client_id"
.\dist\dp032-test-20261020-r2\DeskPilot\DeskPilot.exe
```

Do not create, use, document, or store a Spotify client secret. Run `connect spotify` once from DeskPilot to open the browser-based PKCE authorization flow.

## First-Run Behavior

User-created data is not bundled into the application. DeskPilot keeps settings, notes, and reminders under:

```text
~/Documents/DeskPilot/
```

If the experimental connector is explicitly connected, its Spotify token is stored under this user-data area as a Windows DPAPI-protected file for the current user. Public media controls do not require that file. The build does not bundle Spotify tokens, OAuth callback data, settings, notes, reminders, audio recordings, or local model caches.

On first launch, **Voice setup** lets the user select/test a microphone and prepare the local openWakeWord `hey_jarvis` and faster-whisper multilingual `tiny` models. Missing files download in the background with stage/status feedback. Both local models are prepared even if optional cloud providers are retained, so local fallback is available. These model caches are local machine state and are intentionally not committed or bundled from a developer workstation. After saving setup, start listening explicitly from the tray.

Wake-word ONNX files are downloaded from fixed upstream release URLs into `%LOCALAPPDATA%\DeskPilot\models\openwakeword`. The app passes explicit paths for the wake, spectrogram, and embedding models; it never writes models into the installation directory. Downloads use a timeout and temporary files, and interrupted transfers are not promoted into the cache. Local transcription uses the normal Hugging Face user cache. Old wake files in a developer `.venv` are not copied into the package.

Native voice command transcription uses the local `voice_transcription_provider` setting:

- `auto`: try local transcription first; try cloud only on local failure or empty text, with consent and a key
- `local`: always use local `faster-whisper`
- `openai`: prefer OpenAI with consent and a key; fall back locally if unavailable

DeskPilot sends only the already-recorded bounded command WAV after wake-word activation. It does not stream continuous microphone audio, does not attach notes/reminders/settings as context, and does not retain recordings; temporary transcription WAV files are removed after processing.

Natural-language command understanding uses the local `voice_command_interpreter_provider` setting:

- `auto`: use local phrase classification first; try cloud for unknown phrases only, with consent and a key. Local clarifications remain local
- `local`: offline example-based media phrase classification after exact routing fails
- `openai`: prefer OpenAI interpretation with consent and a key; fall back to the local classifier on failure or unknown

The interpreter sends only the current transcript and static allowed-command metadata, uses `store=false`, and does not use OpenAI built-in tools.

## What Is Bundled

The build script packages the native tray app entrypoint and required Python dependencies for:

- PySide6 tray and overlay UI
- local microphone capture through `sounddevice`
- wake-word integration through `openwakeword`
- local transcription through `faster-whisper`
- optional OpenAI transcription and natural-language interpretation through the official `openai` SDK
- Windows media session controls through the `winrt` namespace packages
- retained experimental Spotify Web API controls implemented with the Python standard library
- local text-to-speech through `pyttsx3`

It does not bundle secrets, notes, reminders, settings, audio recordings, or local model cache directories.

## Troubleshooting

- If `PyInstaller is not installed`, run `python -m pip install -e ".[dev]"`.
- For console diagnostics, run the source with `.\.venv\Scripts\python.exe -m deskpilot_backend.desktop`; the packaged executable is built with `--noconsole`.
- If OpenAI transcription does not run, confirm `OPENAI_API_KEY` is set in the same PowerShell session used to launch DeskPilot.
- If `open spotify` or `play music` reports an opening error, confirm Spotify Desktop is installed and Windows handles the `spotify:` protocol.
- If media controls report no active Windows session, open a player, start a song once, and retry. Do not use `connect spotify` to resolve this local session error.
- If Windows media support is missing, reinstall project dependencies in `.venv` and rebuild before testing a packaged artifact.
- If the experimental `connect spotify` command fails, check its Client ID and exact redirect URI `http://127.0.0.1:8765/callback`. Those requirements apply only to the experimental API path.
- If local transcription fails on first use, confirm the machine can download/cache the multilingual `tiny` model or that the model is already available in the local Hugging Face cache.
- If audio capture fails, check Windows microphone privacy permissions and the default recording device.
- Use **Voice setup → Refresh** to select and test a reconnected or replacement microphone. Changing a selection requires another test before saving.
- If local TTS fails, verify Windows SAPI voices are available on the machine.

## Clean-Machine Checklist

Copy the ZIP to a Windows x64 machine/VM without Python or this repository. Extract it into a normal user-accessible folder, then:

- Launch as a standard user and complete Voice setup, including fresh model downloads.
- Quit and relaunch; verify settings persist and cached models work without downloading again.
- Test wake word, command transcription, SAPI speech, tray/overlay, and microphone stop/quit.
- With Spotify Desktop installed, test open/play/pause/next/previous/mute/volume and the no-session response.
- Verify no developer credentials, settings, or cached models are needed.

Record Windows version, architecture, package build ID, and results before moving on to an installer.

## Processing Consent (DP-034)

Local is the default. Both cloud providers require `cloud_processing_allowed=true` and `OPENAI_API_KEY`. Voice setup explains the upload and potential usage charges before opt-in. Old settings and a pre-existing key do not grant consent. Selecting Local revokes permission. See [DP-034](dp-034-hybrid-phrases.md) for mode semantics, language support and validation limitations.
