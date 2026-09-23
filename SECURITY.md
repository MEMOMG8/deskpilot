# Security Policy

DeskPilot is a local-first Windows assistant. Its security model is based on deterministic command parsing, explicit allowlists, and local-only storage.

## Safety Model

DeskPilot does not execute arbitrary user text. Supported commands are normalized and matched against deterministic command tables. Executable actions are handled by an explicit allowlist in `actions.py`.

DeskPilot does not use `shell=True`, does not accept arbitrary executable paths, does not accept spoken filesystem paths, and does not execute user-provided URLs. Fixed-site commands use exact HTTPS URLs. Search commands URL-encode the query into a trusted search endpoint.

Custom aliases can only map a user phrase to an existing fixed command ID. Aliases cannot target arbitrary executables, paths, URLs, shell commands, media controls, parameterized search, notes, or reminders.

## Local Storage

DeskPilot stores local app data under `~/Documents/DeskPilot`:

- Settings: `~/Documents/DeskPilot/settings.json`
- Notes: `~/Documents/DeskPilot/notes/*.txt`
- Reminders: `~/Documents/DeskPilot/reminders.json`

These files are local user data and should not be committed to Git. Audio recordings are processed in memory for microphone capture and should not be committed if manually created during testing.

## Local Processing

DeskPilot uses local components for speech and wake-word behavior:

- Wake word: openWakeWord local "hey_jarvis" model
- Speech-to-text: local `faster-whisper` model
- Text-to-speech: local Windows SAPI through `pyttsx3`

DeskPilot does not send audio, notes, reminders, settings, or commands to a cloud AI service.

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
