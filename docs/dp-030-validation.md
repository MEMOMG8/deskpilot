# DP-030: Local Spotify Desktop and Windows Media

Validation record updated 2026-10-19. Implementation, automated checks, and the source-app laptop checklist are complete. The owner confirmed the core Spotify flow, mute/volume, repeated pause, and previous while paused/from the start of a track. Packaged-app and clean-machine validation remain pending. This is not a public-release approval.

## Implemented Behavior

| Command | Behavior |
| --- | --- |
| `open spotify` | Exact normalized phrase; opens the fixed `spotify:` protocol and reports launch failures. |
| `play music` | Opens Spotify if no Spotify session is registered, then requests play on the current Windows media session. |
| `pause music` | Explicit pause; no play/pause toggle. |
| `next track` / `next song` | Requests next on the current Windows session. |
| `previous track` / `previous song` | Requests previous on the current Windows session. For an advanced Spotify track, first seeks to its start and waits for acknowledgement, then sends previous once. |
| `mute` / `mute volume` | Toggles system mute through the existing fixed key. |
| `volume up` / `turn volume up` | Raises system volume through the existing fixed key. |
| `volume down` / `turn volume down` | Lowers system volume through the existing fixed key. |

The public media path does not use Spotify Web API, OAuth, tokens, developer credentials, or UI click automation. `spotify.py` and explicit API commands remain experimental and still appear in help. Settings validation rejects aliases that shadow built-ins, including `connect spotify` and `pause spotify`.

The Windows adapter has lazy imports and injectable fakes. Its three Windows-only dependencies are declared in `pyproject.toml`; Foundation.Collections is needed to enumerate sessions and was the missing dependency behind the initial manual-test failure. The build script now collects `winrt`, but a fresh distribution has not yet been tested.

## Automated Verification

Run on 2026-10-19 in the repository `.venv`:

- Full suite: **427 passed**, one third-party Starlette/AnyIO deprecation warning.
- `compileall` over `src` and `tests`: passed.
- `pip check`: no broken requirements.

The suite used temporary settings/home directories, removed cloud credential variables from the test process, and disabled the pytest cache. Compilation used a temporary bytecode directory. No user settings or credentials were changed.

Coverage includes exact `open spotify` routing, public play without Spotify service/token/HTTP calls, explicit repeated pause, no session, launch/control failures, reserved aliases, missing WinRT dependencies, and Spotify previous seek/acknowledgement/rejection cases. Most native behavior is tested with fakes; passing tests alone do not verify a packaged executable or all Windows/player combinations.

To rerun in an activated development environment:

```powershell
python -m pytest
python -m compileall src tests
python -m pip check
git diff --check
```

## Manual Evidence

These outcomes are owner-reported in the development conversation, not inferred from unit tests:

| Case | Status |
| --- | --- |
| Open Spotify from the source app; hear opening feedback | Confirmed |
| `play music` plays and gives active-player feedback | Confirmed |
| `pause music` pauses and gives active-player feedback | Confirmed |
| `next track` changes tracks | Confirmed |
| Advanced track: one `previous track` goes to the preceding song after the final fix | Confirmed |
| Spotify closed/no media session: pause gives a clear no-session message | Confirmed |
| `mute`, `volume up`, `volume down` | Confirmed by owner on 2026-10-19 |
| Repeat pause while already paused | Confirmed by owner on 2026-10-19; stays paused |
| Final previous behavior while paused and from the start of a track | Confirmed by owner on 2026-10-19; goes back one track per command |
| Launch with missing Spotify protocol; rejected player command | Automated coverage; clean-machine checks pending |
| Newly built distribution on a machine without Python/repository | Pending |

## Completed Laptop Checklist

The owner confirmed all laptop checklist cases on 2026-10-19. The steps below are retained for future regression testing.

Quit any other DeskPilot instance first to avoid duplicate listeners. Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m deskpilot_backend.desktop
```

Choose **Start wake word listening** in the tray. For each command say **Hey Jarvis**, wait for the cue, then speak the command. Use the current source, not the old executable in `dist/`.

Mute, volume up, and volume down passed the owner's manual test, along with these edge cases:

1. Say `pause music` twice; confirm the second request leaves playback paused.
2. With a playlist that has a previous song, test one `previous track` while paused, and again from the beginning of a track. Each should go back one song.

Report any failure with the spoken command, player state, observed result, and DeskPilot's response. Do not include tokens or other private data.

## Known Limits

- Windows selects the current session. Another player can receive play/pause/track requests even if Spotify is open.
- A first launch may have no session or loaded song; opening Spotify does not select content. Start a song once when prompted.
- Session presence is used to decide whether to launch Spotify; an open app without a registered session may receive another protocol-open request.
- Spotify previous depends on seeking support and timeline updates. If preparation fails, DeskPilot reports an error. A successful seek followed by a failed skip can leave the current song at its start.
- A successful native call means Windows/the player accepted the request; it does not guarantee audible output, network availability, or a playable preceding song.
- Mute/volume are system keys and do not need a session. The older direct API `media_key/play_pause` action remains allowlisted for compatibility; public `pause music` does not route to it.
- No installer, onboarding, autostart, new UI, fresh package, or public publication was added in DP-030.

## Next Milestones

1. DP-030 source implementation and laptop validation are complete. Commit this reviewed checkpoint only when the owner authorizes a commit.
2. Define DP-031 as minimal first-run setup: microphone selection/test, local voice-model readiness with download/error feedback, tray/listening instructions, and a short supported-command guide. Acceptance: a fresh user can reach the first successful voice command without editing JSON or configuring Spotify API credentials.
3. Build a new Windows artifact and test on a clean machine/profile without Python, developer caches, or repository access. Verify the WinRT namespaces, model downloads, TTS, microphone, tray/overlay, and the same media checklist.
4. Before a public download, decide installer/update/uninstall behavior, review bundled dependency and model redistribution terms, prepare privacy/help text, and evaluate code signing. Keep startup with Windows and additional apps in later work unless scope is explicitly changed.
