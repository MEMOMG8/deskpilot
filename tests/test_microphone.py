import io
import wave
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from deskpilot_backend.main import (
    app,
    get_audio_recorder,
    get_process_launcher,
    get_speech_engine_factory,
    get_transcription_service,
)
from deskpilot_backend.microphone import (
    AdaptiveRecordingConfig,
    MicrophoneError,
    NoSpeechDetectedError,
    SAMPLE_RATE,
    capture_adaptive_speech_pcm,
    capture_adaptive_speech_wav,
    encode_wav,
    frame_energy,
)
from deskpilot_backend.models import TranscriptionResponse


class FakeTranscriptionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        filename: str | None = None,
    ) -> TranscriptionResponse:
        self.calls.append(
            {
                "audio_bytes": audio_bytes,
                "content_type": content_type,
                "filename": filename,
            }
        )
        return TranscriptionResponse(
            status="completed",
            message="Transcription completed.",
            text="open calculator",
            language="en",
        )


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
        return object()


class FakeSpeechEngine:
    def __init__(self) -> None:
        self.spoken_text: list[str] = []
        self.completed = False

    def say(self, text: str) -> None:
        self.spoken_text.append(text)

    def runAndWait(self) -> None:
        self.completed = True


class FakeRecorder:
    def __init__(self, audio_bytes: bytes) -> None:
        self.audio_bytes = audio_bytes
        self.durations: list[int] = []

    def __call__(self, duration_seconds: int) -> bytes:
        self.durations.append(duration_seconds)
        return self.audio_bytes


def pcm_frame(amplitude: int, samples: int = 1600) -> bytes:
    return int(amplitude).to_bytes(2, "little", signed=True) * samples


def frame_source(frames: list[bytes]):
    def source(frame_samples: int, max_frames: int):
        yield from frames[:max_frames]

    return source


@contextmanager
def mocked_microphone_dependencies(
    recorder: object,
    transcription_service: FakeTranscriptionService,
    launcher: RecordingLauncher,
    speech_engine_factory: object | None = None,
) -> Iterator[None]:
    app.dependency_overrides[get_audio_recorder] = lambda: recorder
    app.dependency_overrides[get_transcription_service] = lambda: transcription_service
    app.dependency_overrides[get_process_launcher] = lambda: launcher

    if speech_engine_factory is not None:
        app.dependency_overrides[get_speech_engine_factory] = (
            lambda: speech_engine_factory
        )

    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_microphone_command_records_four_seconds_and_uses_voice_flow() -> None:
    wav_audio = encode_wav(b"\x00\x00" * 16000)
    recorder = FakeRecorder(wav_audio)
    transcription_service = FakeTranscriptionService()
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_microphone_dependencies(recorder, transcription_service, launcher):
        response = client.post(
            "/api/v1/microphone/commands",
            json={"duration_seconds": 4},
        )

    assert response.status_code == 200
    assert response.json()["assistant"]["status"] == "executed"
    assert recorder.durations == [4]
    assert transcription_service.calls == [
        {
            "audio_bytes": wav_audio,
            "content_type": "audio/wav",
            "filename": "microphone.wav",
        }
    ]
    assert launcher.commands == [["calc.exe"]]


def test_microphone_command_forwards_speak_true() -> None:
    recorder = FakeRecorder(encode_wav(b"\x00\x00" * 16000))
    transcription_service = FakeTranscriptionService()
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_microphone_dependencies(
        recorder,
        transcription_service,
        launcher,
        speech_engine_factory=lambda: engine,
    ):
        response = client.post(
            "/api/v1/microphone/commands",
            json={"duration_seconds": 4, "speak": True},
        )

    assert response.status_code == 200
    assert response.json()["assistant"]["speech_result"] == "completed"
    assert engine.spoken_text == ["Opening Calculator."]
    assert launcher.commands == [["calc.exe"]]


def test_microphone_command_rejects_invalid_durations() -> None:
    client = TestClient(app)

    too_short = client.post(
        "/api/v1/microphone/commands",
        json={"duration_seconds": 0},
    )
    too_long = client.post(
        "/api/v1/microphone/commands",
        json={"duration_seconds": 11},
    )

    assert too_short.status_code == 422
    assert too_long.status_code == 422


def test_microphone_failure_stops_before_transcription_action_and_speech() -> None:
    class FailingRecorder:
        def __call__(self, duration_seconds: int) -> bytes:
            raise MicrophoneError("Local microphone recording is unavailable.")

    class MustNotTranscribe(FakeTranscriptionService):
        def transcribe(
            self,
            audio_bytes: bytes,
            *,
            content_type: str | None,
            filename: str | None = None,
        ) -> TranscriptionResponse:
            raise AssertionError("transcription should not run")

    def speech_must_not_run() -> FakeSpeechEngine:
        raise AssertionError("speech should not run")

    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_microphone_dependencies(
        FailingRecorder(),
        MustNotTranscribe(),
        launcher,
        speech_engine_factory=speech_must_not_run,
    ):
        response = client.post(
            "/api/v1/microphone/commands",
            json={"duration_seconds": 4, "speak": True},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Local microphone recording is unavailable."}
    assert launcher.commands == []


def test_adaptive_capture_detects_speech_onset_preroll_and_end_silence() -> None:
    quiet = pcm_frame(0)
    speech = pcm_frame(4000)
    config = AdaptiveRecordingConfig(
        max_duration_seconds=3,
        frame_duration_ms=100,
        energy_threshold=1000,
        initial_speech_timeout_seconds=1,
        end_silence_ms=200,
        min_speech_ms=200,
        pre_roll_ms=400,
        speech_start_frames=2,
    )
    frames = [quiet, quiet, speech, speech, speech, quiet, quiet, quiet]

    captured = capture_adaptive_speech_pcm(
        config,
        frame_source=frame_source(frames),
    )

    assert captured[0] == quiet
    assert captured[1] == quiet
    assert captured[2] == speech
    assert captured[-2:] == [quiet, quiet]


def test_adaptive_capture_times_out_without_speech() -> None:
    config = AdaptiveRecordingConfig(
        max_duration_seconds=3,
        frame_duration_ms=100,
        energy_threshold=1000,
        initial_speech_timeout_seconds=0.3,
    )

    try:
        capture_adaptive_speech_pcm(
            config,
            frame_source=frame_source([pcm_frame(999)] * 10),
        )
    except NoSpeechDetectedError as error:
        assert str(error) == "I didn't hear a command."
    else:
        raise AssertionError("Expected NoSpeechDetectedError")


def test_adaptive_capture_enforces_minimum_speech_duration() -> None:
    quiet = pcm_frame(0)
    speech = pcm_frame(4000)
    config = AdaptiveRecordingConfig(
        max_duration_seconds=3,
        frame_duration_ms=100,
        energy_threshold=1000,
        initial_speech_timeout_seconds=1,
        end_silence_ms=200,
        min_speech_ms=500,
        pre_roll_ms=100,
        speech_start_frames=2,
    )

    try:
        capture_adaptive_speech_pcm(
            config,
            frame_source=frame_source([speech, speech, quiet, quiet]),
        )
    except NoSpeechDetectedError:
        return

    raise AssertionError("Expected short speech to be rejected")


def test_adaptive_capture_never_exceeds_hard_maximum_duration() -> None:
    speech = pcm_frame(4000)
    config = AdaptiveRecordingConfig(
        max_duration_seconds=1,
        frame_duration_ms=100,
        energy_threshold=1000,
        initial_speech_timeout_seconds=1,
        min_speech_ms=200,
        speech_start_frames=2,
    )

    captured = capture_adaptive_speech_pcm(
        config,
        frame_source=frame_source([speech] * 30),
    )

    assert len(captured) == config.max_frames


def test_adaptive_capture_rejects_noisy_near_threshold_frames() -> None:
    config = AdaptiveRecordingConfig(
        max_duration_seconds=2,
        frame_duration_ms=100,
        energy_threshold=1000,
        initial_speech_timeout_seconds=0.5,
        speech_start_frames=2,
    )

    try:
        capture_adaptive_speech_pcm(
            config,
            frame_source=frame_source([pcm_frame(999)] * 10),
        )
    except NoSpeechDetectedError:
        return

    raise AssertionError("Expected near-threshold frames to be ignored")


def test_adaptive_capture_returns_wav_for_final_segment_only() -> None:
    speech = pcm_frame(4000)
    quiet = pcm_frame(0)
    config = AdaptiveRecordingConfig(
        max_duration_seconds=2,
        frame_duration_ms=100,
        energy_threshold=1000,
        initial_speech_timeout_seconds=1,
        end_silence_ms=200,
        min_speech_ms=200,
        speech_start_frames=2,
    )

    wav_audio = capture_adaptive_speech_wav(
        config,
        frame_source=frame_source([quiet, speech, speech, quiet, quiet]),
    )

    with wave.open(io.BytesIO(wav_audio), "rb") as wav_file:
        assert wav_file.getframerate() == SAMPLE_RATE
        assert wav_file.getnchannels() == 1
        assert wav_file.getnframes() > 0


def test_frame_energy_is_deterministic_for_pcm_frames() -> None:
    assert frame_energy(pcm_frame(0)) == 0
    assert frame_energy(pcm_frame(2000)) == 2000
