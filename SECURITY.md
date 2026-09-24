# Security Policy

DeskPilot is a local-first Windows assistant. Its security model is based on deterministic command parsing, optional constrained cloud interpretation, explicit allowlists, and local-only storage.

## Safety Model

DeskPilot does not execute arbitrary user text. Supported commands are normalized and matched against deterministic command tables. Executable actions are handled by an explicit allowlist in `actions.py`.

DeskPilot does not use `shell=True`, does not accept arbitrary executable paths, does not accept spoken filesystem paths, and does not execute user-provided URLs. Fixed-site commands use exact HTTPS URLs. Search commands URL-encode the query into a trusted search endpoint.

When enabled, natural-language command understanding uses OpenAI Responses function calling only after deterministic routing fails. Requests use `store=false`, strict function schemas, `parallel_tool_calls=false`, and no built-in OpenAI tools such as web search, computer use, code interpreter, MCP, or shell tools. Returned tool arguments are not trusted; local code validates them through the existing router and allowlisted executor before anything can run.

Custom aliases can only map a user phrase to an existing fixed command ID. Aliases cannot target arbitrary executables, paths, URLs, shell commands, media controls, parameterized search, notes, or reminders.

## Local Storage

DeskPilot stores local app data under `~/Documents/DeskPilot`:

- Settings: `~/Documents/DeskPilot/settings.json`
- Notes: `~/Documents/DeskPilot/notes/*.txt`
- Reminders: `~/Documents/DeskPilot/reminders.json`

These files are local user data and should not be committed to Git. Audio recordings are processed in memory for microphone capture and should not be committed if manually created during testing.

## Local Processing

DeskPilot uses local components for wake-word behavior, action execution, and text-to-speech:

- Wake word: openWakeWord local "hey_jarvis" model
- Speech-to-text: local `faster-whisper` model, or optional OpenAI `gpt-transcribe` for one already-recorded bounded command WAV
- Text-to-speech: local Windows SAPI through `pyttsx3`
- Command understanding: deterministic local parser first; optional OpenAI Responses function calling only for unknown natural-language phrasing

DeskPilot does not stream continuous microphone audio. It does not send notes, reminders, settings, history, file contents, local paths, or API keys to OpenAI as context. It must never log, print, store, or commit `OPENAI_API_KEY`.

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
