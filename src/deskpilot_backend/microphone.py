import io
import math
import wave
from array import array
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from sys import byteorder

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
DTYPE = "int16"
DEFAULT_FRAME_DURATION_MS = 30
DEFAULT_ENERGY_THRESHOLD = 500
DEFAULT_INITIAL_SPEECH_TIMEOUT_SECONDS = 2.0
DEFAULT_END_SILENCE_MS = 800
DEFAULT_MIN_SPEECH_MS = 300
DEFAULT_PRE_ROLL_MS = 200
DEFAULT_SPEECH_START_FRAMES = 3

AudioRecorder = Callable[[int], bytes]
AudioFrameSource = Callable[[int, int], Iterable[bytes]]


class MicrophoneError(RuntimeError):
    """Raised when local microphone recording cannot complete safely."""


class NoSpeechDetectedError(MicrophoneError):
    """Raised when adaptive recording times out before a command is heard."""


@dataclass(frozen=True)
class AdaptiveRecordingConfig:
    max_duration_seconds: int
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS
    energy_threshold: int = DEFAULT_ENERGY_THRESHOLD
    initial_speech_timeout_seconds: float = DEFAULT_INITIAL_SPEECH_TIMEOUT_SECONDS
    end_silence_ms: int = DEFAULT_END_SILENCE_MS
    min_speech_ms: int = DEFAULT_MIN_SPEECH_MS
    pre_roll_ms: int = DEFAULT_PRE_ROLL_MS
    speech_start_frames: int = DEFAULT_SPEECH_START_FRAMES

    @property
    def frame_samples(self) -> int:
        return max(1, int(SAMPLE_RATE * self.frame_duration_ms / 1000))

    @property
    def max_frames(self) -> int:
        return max(1, math.ceil(self.max_duration_seconds * 1000 / self.frame_duration_ms))

    @property
    def initial_timeout_frames(self) -> int:
        return max(
            1,
            math.ceil(self.initial_speech_timeout_seconds * 1000 / self.frame_duration_ms),
        )

    @property
    def end_silence_frames(self) -> int:
        return max(1, math.ceil(self.end_silence_ms / self.frame_duration_ms))

    @property
    def min_speech_frames(self) -> int:
        return max(1, math.ceil(self.min_speech_ms / self.frame_duration_ms))

    @property
    def pre_roll_frames(self) -> int:
        return max(0, math.ceil(self.pre_roll_ms / self.frame_duration_ms))


def record_microphone_wav(duration_seconds: int) -> bytes:
    try:
        return _record_microphone_wav(duration_seconds)
    except Exception as error:
        raise MicrophoneError("Local microphone recording is unavailable.") from error


def record_adaptive_microphone_wav(duration_seconds: int) -> bytes:
    config = AdaptiveRecordingConfig(max_duration_seconds=duration_seconds)
    try:
        return capture_adaptive_speech_wav(config)
    except NoSpeechDetectedError:
        raise
    except Exception as error:
        raise MicrophoneError("Local microphone recording is unavailable.") from error


def _record_microphone_wav(duration_seconds: int) -> bytes:
    import sounddevice

    frame_count = duration_seconds * SAMPLE_RATE
    recording = sounddevice.rec(
        frame_count,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )
    sounddevice.wait()
    return encode_wav(recording.tobytes())


def capture_adaptive_speech_wav(
    config: AdaptiveRecordingConfig,
    *,
    frame_source: AudioFrameSource | None = None,
) -> bytes:
    frames = capture_adaptive_speech_pcm(
        config,
        frame_source=frame_source or sounddevice_frame_source,
    )
    return encode_wav(b"".join(frames))


def capture_adaptive_speech_pcm(
    config: AdaptiveRecordingConfig,
    *,
    frame_source: AudioFrameSource,
) -> list[bytes]:
    pre_roll: list[bytes] = []
    pending_speech_frames = 0
    captured: list[bytes] = []
    silence_frames = 0
    captured_frames_after_onset = 0
    speech_started = False

    for frame_index, frame in enumerate(
        frame_source(config.frame_samples, config.max_frames),
        start=1,
    ):
        is_speech = frame_energy(frame) >= config.energy_threshold

        if not speech_started:
            pre_roll.append(frame)
            if config.pre_roll_frames and len(pre_roll) > config.pre_roll_frames:
                pre_roll.pop(0)

            if is_speech:
                pending_speech_frames += 1
            else:
                pending_speech_frames = 0

            if pending_speech_frames >= config.speech_start_frames:
                speech_started = True
                captured.extend(pre_roll)
                captured_frames_after_onset = pending_speech_frames
                silence_frames = 0
                pre_roll = []
                continue

            if frame_index >= config.initial_timeout_frames:
                raise NoSpeechDetectedError("I didn't hear a command.")

            continue

        captured.append(frame)
        captured_frames_after_onset += 1

        if is_speech:
            silence_frames = 0
        else:
            silence_frames += 1

        if silence_frames >= config.end_silence_frames:
            if captured_frames_after_onset < config.min_speech_frames:
                raise NoSpeechDetectedError("I didn't hear a command.")
            return captured

    if not speech_started or captured_frames_after_onset < config.min_speech_frames:
        raise NoSpeechDetectedError("I didn't hear a command.")

    return captured


def sounddevice_frame_source(
    frame_samples: int,
    max_frames: int,
) -> Iterable[bytes]:
    import sounddevice

    with sounddevice.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=frame_samples,
    ) as stream:
        for _ in range(max_frames):
            data, overflowed = stream.read(frame_samples)
            if overflowed:
                raise MicrophoneError("Local microphone recording is unavailable.")
            yield bytes(data)


def frame_energy(pcm_frame: bytes) -> float:
    if not pcm_frame:
        return 0.0

    samples = array("h")
    samples.frombytes(pcm_frame)
    if byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0

    square_sum = sum(sample * sample for sample in samples)
    return math.sqrt(square_sum / len(samples))


def encode_wav(pcm_audio: bytes) -> bytes:
    wav_buffer = io.BytesIO()

    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_audio)

    return wav_buffer.getvalue()
