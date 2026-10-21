# Security Policy

DeskPilot is a local-first Windows assistant. Its security model is based on deterministic command parsing, a conservative offline media classifier, optional constrained cloud interpretation, explicit allowlists, and local-only storage.

## Safety Model

DeskPilot does not execute arbitrary user text. Supported commands are normalized and matched against deterministic command tables. Executable actions are handled by an explicit allowlist in `actions.py`.

DeskPilot does not use `shell=True`, does not accept arbitrary executable paths, does not accept spoken filesystem paths, and does not execute user-provided URLs. Fixed-site commands use exact HTTPS URLs. Search commands URL-encode the query into a trusted search endpoint.

When enabled, natural-language command understanding uses OpenAI Responses function calling only after deterministic routing fails. Requests use `store=false`, strict function schemas, `parallel_tool_calls=false`, and no built-in OpenAI tools such as web search, computer use, code interpreter, MCP, or shell tools. Returned tool arguments are not trusted; local code validates them through the existing router and allowlisted executor before anything can run.

Custom aliases loaded from settings can only map a user phrase to an existing fixed command ID. They cannot replace built-in commands, including `open spotify`, `connect spotify`, and `pause spotify`. Aliases cannot target arbitrary executables, paths, URLs, shell commands, media controls, parameterized search, notes, or reminders.

The public `open spotify` command opens only the fixed `spotify:` protocol. `play music` can open Spotify and then sends an explicit play request to the current Windows media session. Pause, next, and previous also use local Windows media sessions; pause never uses a play/pause toggle. The Spotify-specific previous adjustment uses local seek followed by one previous request. Mute and volume use fixed system media keys. These paths do not use Spotify OAuth, tokens, HTTP, or UI click automation. Windows selects the current session, which may belong to another player.

The experimental Web API commands, such as `connect spotify`, `play spotify`, and `pause spotify`, remain behind the existing allowlist. They are separate from the public media path and affect the active Spotify device.

Experimental Spotify OAuth uses Authorization Code with PKCE, a cryptographically random verifier, a cryptographically random state, and the fixed redirect URI `http://127.0.0.1:8765/callback`. DeskPilot requests only `user-read-playback-state user-modify-playback-state`, uses only `SPOTIFY_CLIENT_ID`, and does not use or store a Spotify client secret.

## Local Storage

DeskPilot stores local app data under `~/Documents/DeskPilot`:

- Settings: `~/Documents/DeskPilot/settings.json`
- Notes: `~/Documents/DeskPilot/notes/*.txt`
- Reminders: `~/Documents/DeskPilot/reminders.json`
- Experimental Spotify protected token, only after connecting: `~/Documents/DeskPilot/spotify.bin`

The Spotify token file is encrypted with Windows DPAPI for the current user. Plaintext tokens, OAuth authorization codes, PKCE verifiers, sensitive headers, notes, reminders, settings, and audio recordings should not be committed to Git. Audio recordings are processed in memory for microphone capture and should not be committed if manually created during testing.

## Local Processing

DeskPilot uses local components for wake-word behavior, action execution, and text-to-speech:

- Wake word: openWakeWord local "hey_jarvis" model
- Speech-to-text: local `faster-whisper` model, or optional OpenAI `gpt-transcribe` for one already-recorded bounded command WAV
- Text-to-speech: local Windows SAPI through `pyttsx3`
- Command understanding: deterministic parser first, then offline EN/ES media classification or explicitly consented cloud interpretation; all results return through the router

DeskPilot does not stream continuous microphone audio. It does not send notes, reminders, settings, history, file contents, local paths, or API keys to OpenAI as context. It must never log, print, store, or commit `OPENAI_API_KEY`, `SPOTIFY_CLIENT_ID`, Spotify access tokens, Spotify refresh tokens, OAuth authorization codes, PKCE verifiers, or sensitive request headers.

Voice setup pauses wake listening. Its explicit three-second microphone test measures PCM energy in memory and never transcribes audio or executes commands. Model preparation downloads missing local model files without capturing audio. Saving setup does not enable listening; the user starts it from the tray. Cancelling setup does not persist its selections.

The selected microphone is stored by device name and audio-host API, not by an unstable numeric index. Setup saves only its owned fields using a temporary file and atomic replacement, preserves other preferences, and refuses to replace malformed or unsupported settings.

## Supported Platforms

DeskPilot targets Windows. Windows-specific actions return controlled errors on unsupported platforms instead of silently succeeding.

## Responsible Disclosure

If you find a security issue, please open a private report through the repository owner's preferred GitHub security reporting channel if available. If private reporting is not available, contact the maintainer directly before filing a public issue.

Please include:

- Affected version or commit
- Steps to reproduce
- Expected and actual behavior
- Any logs that do not contain secrets or personal data

Do not include private notes, reminders, settings, audio recordings, access tokens, or other sensitive local files in reports.

## Processing Consent (DP-034)

Local is the default. Both cloud providers require `cloud_processing_allowed=true` and `OPENAI_API_KEY`. Voice setup explains the upload and potential usage charges before opt-in. Old settings and a pre-existing key do not grant consent. Selecting Local revokes permission. See [DP-034](docs/dp-034-hybrid-phrases.md) for mode semantics, language support and validation limitations.
