# DeskPilot

DeskPilot is a local-first Windows voice assistant that demonstrates safe native automation with deterministic command routing and explicit allowlisted actions.

## Features

- Native Windows tray shell with local wake-word activation: "Hey Jarvis"
- First-run Voice setup: select/test a microphone, prepare local models, and learn the first commands
- Per-user Windows test installer with a Start menu shortcut and updates that preserve user data ([DP-033](docs/dp-033-installer.md))
- Push-to-talk browser demo and API endpoints for typed, uploaded-audio, and microphone commands
- Configurable command transcription: automatic OpenAI `gpt-transcribe` when `OPENAI_API_KEY` is set, or local `faster-whisper` fallback
- Optional OpenAI natural-language command understanding for unsupported phrasing, with strict function schemas and local allowlist validation
- Local Spotify Desktop launch and explicit play/pause/track controls through Windows media sessions, without Spotify API credentials
- Experimental Spotify Web API connection retained separately using Authorization Code with PKCE
- Local Windows SAPI text-to-speech through `pyttsx3`
- Deterministic English command router remains the first path for every command
- Strict allowlisted execution for apps, fixed websites, bounded search, Windows media controls, experimental Spotify API controls, workspace shortcuts, notes, reminders, and settings
- Local notes, reminders, and settings stored under `~/Documents/DeskPilot`
- Unit-tested services with mocked microphone, speech, wake word, process launching, and timers

## Privacy And Safety

DeskPilot is designed to keep actions, storage, wake-word detection, text-to-speech, notes, reminders, and settings local. Audio is captured only after an explicit button press or enabled local wake-word detection.

Native wake-word commands can optionally use OpenAI `gpt-transcribe` for the already-recorded short command WAV. DeskPilot can also optionally use OpenAI Responses function calling to interpret natural English phrasing only after the deterministic router does not recognize a command. DeskPilot never streams continuous microphone audio, does not send notes/reminders/settings/history/file contents as context, and does not write or retain command recordings or cloud requests.

Cloud interpretation never executes actions. It may only propose a strict typed outcome, and local DeskPilot code validates that outcome through the existing command router and allowlisted executor. If OpenAI transcription or interpretation is unavailable, DeskPilot falls back to local behavior when possible.

Safety is enforced with deterministic parsing and explicit allowlists. DeskPilot does not execute arbitrary text, shell commands, paths, URLs, or user-provided executables. Search queries are URL-encoded into trusted search endpoints, and custom aliases may only point to already-supported fixed commands.

The public Spotify Desktop flow opens the fixed `spotify:` protocol and controls the current Windows media session. It requires no Spotify Web API, OAuth, tokens, developer account, or UI click automation. Mute and volume use fixed system media keys.

The older Spotify Web API integration remains experimental. Its `connect spotify` command opens a browser for authorization, requests playback-state and playback-control scopes, and stores the token locally with Windows DPAPI for the current user. Public commands such as `play music` and `pause music` do not invoke that integration.

See [SECURITY.md](SECURITY.md) for the safety model and disclosure guidance.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the API:

```powershell
python -m uvicorn deskpilot_backend.main:app --reload
```

Then visit `http://127.0.0.1:8000/api/v1/health`.

Run the native tray shell:

```powershell
python -m deskpilot_backend.desktop
```

DeskPilot starts in the Windows system tray and opens **Voice setup** until setup is saved. You can reopen it from the tray at any time.

1. Choose a microphone and click **Test microphone · 3 seconds**. Speak normally while watching the input level. This local test does not save or transcribe audio.
2. Click **Prepare voice models**. The window shows the wake-word and local-transcription preparation stages; missing files download in the background. Retry if preparation fails.
3. Leave **Use local transcription and command matching (no cloud)** checked for local operation. Unchecked preserves your existing provider settings.
4. Click **Save setup**, then choose **Start wake word listening** in the tray. Say **Hey Jarvis**, wait for the cue, then say **open calculator**.

Saving does not start listening. **Later** leaves setup incomplete; the next launch or Start request reopens it. Opening setup pauses listening. Use the tray menu to start or stop listening, show/hide the overlay, or quit.

See [DP-031 setup and validation](docs/dp-031-voice-setup.md) for troubleshooting and manual checks.

## Browser Demo

With the API running, open `http://127.0.0.1:8000`, click `Talk (4 seconds)`, and say "open calculator". The browser calls the existing local microphone command endpoint.

## Native Voice Demo

Start the tray app, choose `Start wake word listening`, say "Hey Jarvis", then speak a supported command while the cyan listening border is visible. DeskPilot plays a short local Windows cue when command listening begins, stops the wake-word microphone stream, calibrates briefly against local ambient audio, waits up to 3 seconds for speech onset, keeps a small pre-roll, captures until about 1.1 seconds of trailing silence, then sends only that bounded final command segment to the selected transcription provider. It runs the allowlisted assistant flow, narrates the response with local TTS, hides the border, and resumes wake-word listening if it is still enabled.

If no speech is detected during the bounded initial listening window, DeskPilot does not transcribe anything and gives concise recoverable feedback: `I didn't hear a command.`

Native voice states:

- Cyan: listening for the command
- Amber: processing transcription and the allowlisted action
- Green: completed successfully, then hides
- Red: recoverable error or unknown command, then hides

Voice setup prepares openWakeWord's local `hey_jarvis` model and the `tiny.en` local transcription model before the first command. Already-cached files are reused. openWakeWord code is Apache-2.0 licensed, while its included pre-trained models are licensed CC BY-NC-SA 4.0.

For stronger native command transcription, set `OPENAI_API_KEY` before starting the tray app:

```powershell
$env:OPENAI_API_KEY = "your_api_key_here"
python -m deskpilot_backend.desktop
```

Do not commit API keys. With the default `auto` providers, DeskPilot uses OpenAI only when this environment variable exists; otherwise it preserves local transcription and deterministic command routing. OpenAI usage may incur API cost.

## Spotify Desktop Setup

1. Install Spotify Desktop and sign in through Spotify itself.
2. Start DeskPilot from source and choose `Start wake word listening` in the tray.
3. Say `Hey Jarvis`, wait for the listening cue, then say `open spotify`.
4. Use `play music`, `pause music`, `next track`, and `previous track`. If Windows has no media session, start a song in Spotify once and retry.

No Spotify Developer app, `SPOTIFY_CLIENT_ID`, `connect spotify`, or DeskPilot OAuth token is needed. Windows chooses the current media session, so another active player can receive media commands. `open spotify` only opens the app; it does not select a song.

For the manual validation record and remaining release checks, see [DP-030 validation](docs/dp-030-validation.md).

## Experimental Spotify Web API Setup

This retained integration is separate from the public v0.1 desktop flow. Use the explicit Spotify API commands below only when testing the experimental connector.

Spotify controls are optional. They require a Spotify account with playback-control support, a Spotify Premium account for many playback-control API operations, and an active Spotify device.

1. Create a Spotify Developer app at `https://developer.spotify.com/dashboard`.
2. Add this exact redirect URI to the app:

```text
http://127.0.0.1:8765/callback
```

3. Copy the app's Client ID. Do not create, use, or store a client secret.
4. Start DeskPilot with the Client ID in the environment:

```powershell
$env:SPOTIFY_CLIENT_ID = "your_spotify_client_id"
python -m deskpilot_backend.desktop
```

5. Say or type `connect spotify`. DeskPilot opens your browser for Spotify authorization, accepts one localhost callback on `127.0.0.1:8765`, then stores the protected refresh token under `~/Documents/DeskPilot`.
6. Start playback on a Spotify device, then use experimental commands such as `play spotify`, `spotify status`, `pause spotify`, or `set spotify volume to 50`.

Use `disconnect spotify` to delete the local protected token. DeskPilot never stores plaintext Spotify tokens in `settings.json`.

## Tests

```powershell
python -m pytest
python -m compileall src tests
```

## Documentation

- [Architecture](docs/architecture.md)
- [90-second demo script](docs/demo-script.md)
- [Windows build](docs/windows-build.md)
- [DP-030 validation and release follow-up](docs/dp-030-validation.md)
- [DP-031 voice setup](docs/dp-031-voice-setup.md)
- [DP-032 Windows test distribution](docs/dp-032-windows-build.md)
- [Security](SECURITY.md)

## Local Settings

DeskPilot stores local preferences in `~/Documents/DeskPilot/settings.json`. The file is created only when missing, using this schema:

```json
{
  "version": 1,
  "command_capture_duration_seconds": 4,
  "recording_start_cue_enabled": true,
  "wake_listening_on_startup": false,
  "voice_transcription_provider": "auto",
  "voice_command_interpreter_provider": "auto",
  "default_music_app": "spotify",
  "microphone_device": null,
  "voice_setup_completed": false,
  "custom_aliases": {}
}
```

`command_capture_duration_seconds` is allowed from `2` through `8`; invalid values fall back to `4`. For native wake-word commands, this is the hard maximum adaptive endpointing duration, not a fixed recording length. `recording_start_cue_enabled` controls the local Windows cue before native command listening. `wake_listening_on_startup` starts wake-word listening when the tray shell opens.

`voice_transcription_provider` controls only native wake-word command transcription:

- `auto`: use OpenAI `gpt-transcribe` when `OPENAI_API_KEY` exists, otherwise use local `faster-whisper`
- `local`: always use local `faster-whisper`
- `openai`: prefer OpenAI and fall back locally if cloud transcription is unavailable

Invalid provider values use `auto`.

`voice_command_interpreter_provider` controls natural-language command understanding after deterministic routing fails:

- `auto`: use OpenAI Responses function calling when `OPENAI_API_KEY` exists, otherwise deterministic-only behavior
- `local`: deterministic-only behavior
- `openai`: prefer OpenAI interpretation and show a recoverable message if no key is configured

The interpreter uses `store=false`, strict function schemas, no OpenAI built-in tools, and one tool call. Returned tool arguments are validated locally before any action can run.

`default_music_app` controls the exact `play music` command. Only `spotify` is supported for now; invalid values safely fall back to `spotify`.

`microphone_device` is `null` for the system default, or an object with the selected device's `name` and `hostapi`. Native wake-word listening and command capture resolve that identity each time they open a stream, so a changed numeric device index does not select a different microphone. If a selected device disappears, reopen **Voice setup** and refresh. The development API microphone endpoint continues to use its default input.

`voice_setup_completed` is set only by saving setup after a successful audio-signal test and model preparation. Older settings remain readable and show setup once. Saving updates the setup fields, and optionally the two provider settings when local mode is checked; it preserves aliases and other fields. Malformed or unsupported settings files are not overwritten.

Custom aliases map one fixed phrase to an existing fixed command ID:

```json
{
  "custom_aliases": {
    "open my projects": "open github"
  }
}
```

Aliases cannot replace built-in commands, collide after normalization, or point to executables, paths, URLs, shell commands, media controls, notes, reminders, or parameterized searches. Invalid settings are not rewritten; DeskPilot uses safe defaults and shows a local warning.

## API Endpoints

- `GET /api/v1/health`
- `POST /api/v1/commands`
- `POST /api/v1/actions/execute`
- `POST /api/v1/assistant/commands`
- `POST /api/v1/speech/speak`
- `POST /api/v1/transcriptions`
- `POST /api/v1/voice/commands`
- `POST /api/v1/microphone/commands`

## Supported Commands

Application commands:

- `open calculator`
- `open notepad`
- `open file explorer`
- `open explorer`
- `open settings`
- `open browser`
- `open spotify`
- `open task manager`

Settings commands:

- `open deskpilot settings`

Experimental Spotify Web API commands (not required for local playback):

- `connect spotify`
- `disconnect spotify`
- `spotify status`
- `play spotify`
- `pause spotify`
- `next spotify song`
- `previous spotify song`
- `set spotify volume to 50`

Fixed-site commands:

- `open google`
- `open youtube`
- `open github`

Search commands:

- `search web for deskpilot`
- `search google for python url encoding`
- `search youtube for local voice assistant`
- `search github for fastapi examples`

Notes commands:

- `take a note remember this`
- `note remember this`
- `read latest note`
- `how many notes do I have`
- `open notes folder`

Reminder commands:

- `remind me in one minute to stretch`
- `remind me in 10 minutes to stretch`
- `remind me in twenty five minutes to stretch`
- `list reminders`
- `what are my reminders`

Workspace shortcuts:

- `open downloads`
- `open documents`
- `open desktop`

Information commands:

- `what time is it`
- `what's the time`
- `what is the date`
- `what's today's date`
- `battery status`
- `what is my battery level`
- `memory status`
- `how much memory am I using`
- `disk space`
- `how much disk space do I have`
- `help`
- `what can you do`

Cancel commands:

- `cancel`
- `never mind`

Volume commands:

- `volume up`
- `turn volume up`
- `volume down`
- `turn volume down`
- `mute`
- `mute volume`

Media commands:

- `play music`
- `pause music`
- `next song`
- `next track`
- `previous song`
- `previous track`

`play music` opens Spotify through the fixed `spotify:` target if no Spotify session is registered, then requests play on the current Windows media session. After launching, it waits briefly for a session if none exists. If Windows still has no current session, DeskPilot reports an error and asks you to start a song once.

`pause music` requests an explicit pause, so repeating it cannot toggle playback on. Next and previous target the current Windows media session. For Spotify, `previous track` seeks an advanced track to its start, waits for the position update, then requests previous exactly once; a single voice command goes to the previous track. Other players retain their native previous behavior. Unsupported operations, rejected requests, and missing sessions produce errors instead of success responses.

Mute toggles system mute, and volume commands adjust system volume with fixed Windows media keys; they do not require a playback session. Workspace shortcuts use fixed Windows targets only. Folder shortcuts are derived from known local user directories; DeskPilot never accepts spoken paths. System status commands are read-only and use standard-library or Windows `ctypes` calls.

Only the experimental Spotify commands use Spotify HTTPS endpoints. They remain available in the router and help output for compatibility; `play music` and the public media commands never call them.

Fixed-site commands use exact allowlisted HTTPS URLs. Search commands encode the query into the trusted search site's `q` parameter and open the results in the default browser; DeskPilot does not make direct HTTP requests.

Notes are saved as UTF-8 `.txt` files under `~/Documents/DeskPilot/notes`. Reminders are saved locally in `~/Documents/DeskPilot/reminders.json`, reloaded on startup, and scheduled from saved due times. When a reminder is due, DeskPilot shows a native tray notification and says `Reminder: <text>` with local TTS.
