# DP-034: Local, Cloud and Automatic Phrase Understanding

## Scope

Music and volume phrases in English and Spanish map to eight existing commands:
`open spotify`, `play music`, `pause music`, `next track`, `previous track`,
`volume up`, `volume down`, and `mute`. Their Windows media behavior is unchanged.
There is no Spotify Web API requirement. Other exact commands keep priority.
Built-ins now also take priority over aliases supplied directly to the router.

The local interpreter is a small statistical example classifier using TF-IDF
word/character features and cosine similarity. It is not a conversational LLM,
does not learn from user recordings, and does not download an interpretation
model. `scikit-learn` is now an explicit project dependency because this module
uses it directly (it was already installed through the voice stack).

The classifier rejects unsupported targets, negations and compound requests.
Scores below 0.48 abstain; intermediate scores request clarification; direct
execution requires at least 0.72 similarity and a 0.12 lead over the next intent.
Scores are not calibrated probabilities. All proposals return through the
deterministic router and action allowlist. Clarifications accept only fixed
command choices, including `primera opción`, `segunda opción`, and `cancelar`.
No model output becomes executable code, a path, or an arbitrary URL.

## Modes and Consent

Voice setup saves the same selected mode for transcription and interpretation:

| Mode | Speech transcription | Interpretation after exact routing fails |
| --- | --- | --- |
| Local (default) | Local faster-whisper | Offline media classifier |
| Automatic | Local first; cloud only after local error or empty transcription | Local first; cloud only for unknown results, retaining local clarifications |
| Cloud | Cloud first, local fallback | Cloud first, local fallback on failure or unknown |

Every cloud request requires explicit `cloud_processing_allowed=true` and
`OPENAI_API_KEY`. Older settings default to no consent, even with a key already
in the environment. Selecting Local revokes consent. Missing credentials and
cloud failures produce recoverable feedback where appropriate. Clients use
bounded timeouts (12 seconds for interpretation, 15 for transcription) and no
automatic SDK retries. Automatic cannot detect a plausible but incorrect local
transcript; it does not upload every recording for a second opinion.

Only the current bounded command audio or text is sent. Stored notes, reminders,
settings, files and history are not attached as context; content the user speaks
in the current command can be included. Temporary WAV files are removed after
processing. Cloud interpretation retains strict function schemas, `store=false`,
one tool call, and no built-in tools. Cloud may incur API charges. This milestone
uses the user's configured key; it does not add account onboarding, hosted
billing, or a shared credential to the executable.

## Language and Models

Local transcription now uses multilingual `tiny`, replacing `tiny.en` as the
default. A previously downloaded English-only model does not satisfy this model
requirement; Voice setup downloads the multilingual model when missing. No
global package installation is needed. Choose English or Español for short
commands; automatic language detection is available but less reliable for them.
Wake word remains **Hey Jarvis**. UI, TTS responses, and non-media exact commands
remain in English. This is not a complete Spanish localization.

## Validation

`tests/fixtures/media_intents.json` contains 60 positive, 60 negative and four
ambiguous development phrases. Tests check wrong actions, abstention,
clarification choices, consent, fallbacks, native preference propagation,
language hints, and alias priority. Cloud SDK/network behavior is faked; no
paid live cloud requests are made by these checks.

Run the offline coverage/latency report:

```powershell
.\.venv\Scripts\python.exe -B scripts/evaluate-media-phrases.py
```

The reviewed development set measures regressions, not accuracy on unseen
real-world speech. It was used during development and includes normalized
paraphrases of training examples. Voice recognition under accent/noise and live
cloud behavior require manual acceptance. First classifier use imports sklearn
and fits the small corpus; subsequent calls reuse the cached vectors.

The packaged self-test additionally runs EN/ES classification and a negation
check offline without executing any media command.

### Source validation record — 2026-10-21

- Full suite: **664 passed**, with the existing Starlette/AnyIO deprecation
  warning. Tests used an isolated temporary profile with cloud/Spotify keys
  removed. The final setup-label adjustment also passed all ten UI tests.
- `compileall` passed for source, tests and scripts. `pip check` passed.
- Development phrase report: **54/60 direct correct**, six clarifications,
  zero wrong direct actions; **0/60 negative false actions**. Four ambiguity
  cases also passed. This 90% direct coverage is not real-world accuracy.
- One measured run: 6.06 ms median warm interpretation, 67.09 ms maximum;
  6.95 seconds for the first import/fit. Another isolated cold run took 3.50
  seconds. Timing varies with machine load; neither includes speech recognition.
- Sparse training vectors occupy 77,740 bytes. An isolated Python classifier
  process used 111.2 MiB working set after imports/fit (14.6 MiB before); these
  figures exclude Qt, wake-word and speech models and are not app memory totals.
- Voice setup was rendered offscreen and visually checked with a Windows font.
  No microphone recording or paid cloud call was used in this validation.

Local reports and UI capture are under ignored `build/dp034-validation`.

### Build record

- Build ID: **dp034-test-20261021**. All **eight** frozen runtime/startup checks
  passed with an isolated profile, no cloud credentials and no Python in PATH.
  The local EN/ES classification check passed in the bundled executable.
- Portable ZIP integrity passed. ZIP SHA-256:
  `c195d8fcd8ba1f2cd779fa667dfa7b5ba113608d11f632284f36ac8ea10d95be`.
- Installer creation passed the exact payload inventory and source fingerprint
  checks. Installer SHA-256:
  `f57537389c25c46a4cb10d4015cdce131b9553d1ecb08e591f4aa101a00f39ec`.
- Installer: `dist/dp034-test-20261021/installer/DeskPilot-0.1.0-dp034-test-20261021-setup.exe`.
  Portable ZIP is beside the `installer` directory. These are unsigned local
  test artifacts; no public release was published.
- The unchanged DP-033 installer lifecycle recipe was not rerun for this
  milestone; its earlier eight lifecycle checks remain the prior evidence.
  No production installation or user preferences were changed by these checks.

Build provenance records the pre-checkpoint Git HEAD/dirty state and the exact
source fingerprint. Generated artifacts and reports are ignored by Git.

## Manual Acceptance

1. Quit existing DeskPilot instances from the tray. Install the new DP-034 build
   and launch from Start, or run source with
   `.\.venv\Scripts\python.exe -m deskpilot_backend.desktop` in the repository.
2. Open **Voice setup**. Choose **Local · offline** and **Español**, test the
   microphone, prepare models, and save. Start wake listening explicitly.
3. Say **Hey Jarvis**, wait for the cue, then separately test **abre Spotify**,
   **pon música**, **pausa la canción**, **siguiente canción**, **vuelve a la
   canción anterior**, **sube el volumen**, **baja el volumen**, **silencia el
   sonido**. Media commands use the active Windows player; mute is a toggle.
4. Try **cambia la canción**: it must ask which action, then **segunda opción**
   selects previous. **No pauses la música** must not pause anything.
5. Select English and repeat the existing exact Spotify/media commands, plus
   **pause the song**, **make it louder**, and **open calculator**. The first
   natural phrase may take longer while the classifier initializes.
6. After model preparation, test Local with Internet disconnected. It must keep
   working. Reconnect before opting into a cloud mode.
7. Optional cloud acceptance: configure your own `OPENAI_API_KEY` before app
   launch, select Cloud or Automatic, explicitly consent, and repeat phrases.
   With Cloud, disconnect Internet and check local fallback/recoverable feedback.
   Return to Local and confirm consent is revoked. Never paste the key into a
   report, screenshot, repository, or chat.

The user explicitly deferred DP-033's separate clean Windows profile test.
It remains pending and is not claimed as passed here. The previous portable
build's second-laptop acceptance does not validate this new speech model.

## References

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI speech to text](https://developers.openai.com/api/docs/guides/speech-to-text)
- [scikit-learn text feature extraction](https://scikit-learn.org/stable/modules/feature_extraction.html)
