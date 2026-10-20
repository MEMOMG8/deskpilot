import io
import logging
import math
import wave
from array import array
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from sys import byteorder

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
DTYPE = "int16"
DEFAULT_FRAME_DURATION_MS = 30
DEFAULT_ENERGY_THRESHOLD = 120
DEFAULT_ENERGY_THRESHOLD_CEILING = 350
DEFAULT_AMBIENT_CALIBRATION_MS = 300
DEFAULT_AMBIENT_THRESHOLD_MULTIPLIER = 3.0
DEFAULT_AMBIENT_THRESHOLD_MARGIN = 80
DEFAULT_INITIAL_SPEECH_TIMEOUT_SECONDS = 3.0
DEFAULT_END_SILENCE_MS = 1100
DEFAULT_MIN_SPEECH_MS = 300
DEFAULT_PRE_ROLL_MS = 200
DEFAULT_SPEECH_START_FRAMES = 2

LOGGER = logging.getLogger(__name__)

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
    energy_threshold_ceiling: int = DEFAULT_ENERGY_THRESHOLD_CEILING
    ambient_calibration_ms: int = DEFAULT_AMBIENT_CALIBRATION_MS
    ambient_threshold_multiplier: float = DEFAULT_AMBIENT_THRESHOLD_MULTIPLIER
    ambient_threshold_margin: int = DEFAULT_AMBIENT_THRESHOLD_MARGIN
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
    def calibration_frames(self) -> int:
        if self.ambient_calibration_ms <= 0:
            return 0
        return max(1, math.ceil(self.ambient_calibration_ms / self.frame_duration_ms))

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


def record_adaptive_microphone_wav(
    duration_seconds: int, *, device: dict[str, str] | None = None
) -> bytes:
    config = AdaptiveRecordingConfig(max_duration_seconds=duration_seconds)
    try:
        return capture_adaptive_speech_wav(
            config, frame_source=partial(sounddevice_frame_source, device=device)
        )
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
    calibration_energies: list[float] = []
    active_threshold = float(config.energy_threshold)
    calibrated = config.calibration_frames == 0
    pre_roll: list[bytes] = []
    pending_speech_frames = 0
    captured: list[bytes] = []
    silence_frames = 0
    captured_frames_after_onset = 0
    frames_after_calibration = 0
    speech_started = False

    for frame_index, frame in enumerate(
        frame_source(config.frame_samples, config.max_frames),
        start=1,
    ):
        energy = frame_energy(frame)

        if not calibrated:
            calibration_energies.append(energy)
            LOGGER.debug(
                "Adaptive microphone calibration frame=%s rms=%.1f",
                frame_index,
                energy,
            )
            if len(calibration_energies) >= config.calibration_frames:
                active_threshold = calculate_adaptive_threshold(
                    calibration_energies,
                    floor=config.energy_threshold,
                    ceiling=config.energy_threshold_ceiling,
                    multiplier=config.ambient_threshold_multiplier,
                    margin=config.ambient_threshold_margin,
                )
                calibrated = True
                LOGGER.debug(
                    "Adaptive microphone calibrated frames=%s ambient_rms=%.1f "
                    "threshold=%.1f",
                    len(calibration_energies),
                    percentile(calibration_energies, 0.2),
                    active_threshold,
                )
            continue

        frames_after_calibration += 1
        is_speech = energy >= active_threshold
        LOGGER.debug(
            "Adaptive microphone frame=%s post_calibration_frame=%s rms=%.1f "
            "threshold=%.1f speech=%s started=%s voiced_frames=%s "
            "silence_frames=%s",
            frame_index,
            frames_after_calibration,
            energy,
            active_threshold,
            is_speech,
            speech_started,
            pending_speech_frames,
            silence_frames,
        )

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

            if (
                frames_after_calibration >= config.initial_timeout_frames
                and pending_speech_frames == 0
            ):
                LOGGER.debug(
                    "Adaptive microphone no-speech timeout frames=%s threshold=%.1f",
                    frames_after_calibration,
                    active_threshold,
                )
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
                LOGGER.debug(
                    "Adaptive microphone speech too short frames=%s threshold=%.1f",
                    captured_frames_after_onset,
                    active_threshold,
                )
                raise NoSpeechDetectedError("I didn't hear a command.")
            return captured

    if not speech_started or captured_frames_after_onset < config.min_speech_frames:
        LOGGER.debug(
            "Adaptive microphone ended without enough speech started=%s frames=%s "
            "threshold=%.1f",
            speech_started,
            captured_frames_after_onset,
            active_threshold,
        )
        raise NoSpeechDetectedError("I didn't hear a command.")

    return captured


def sounddevice_frame_source(
    frame_samples: int,
    max_frames: int,
    *,
    device: dict[str, str] | None = None,
) -> Iterable[bytes]:
    import sounddevice
    from deskpilot_backend.audio_devices import resolve_input_device

    with sounddevice.RawInputStream(
        device=resolve_input_device(device, sounddevice),
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

    if len(pcm_frame) % SAMPLE_WIDTH_BYTES:
        raise ValueError("PCM frame must contain complete int16 samples.")

    samples = array("h")
    samples.frombytes(pcm_frame)
    if byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0

    square_sum = sum(sample * sample for sample in samples)
    return math.sqrt(square_sum / len(samples))


def calculate_adaptive_threshold(
    calibration_energies: list[float],
    *,
    floor: int,
    ceiling: int,
    multiplier: float,
    margin: int,
) -> float:
    if not calibration_energies:
        return float(floor)

    ambient = percentile(calibration_energies, 0.2)
    adaptive_threshold = ambient * multiplier + margin
    safe_ceiling = max(floor, ceiling)
    return min(safe_ceiling, max(float(floor), adaptive_threshold))


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, math.floor((len(ordered) - 1) * fraction)),
    )
    return ordered[index]


def encode_wav(pcm_audio: bytes) -> bytes:
    wav_buffer = io.BytesIO()

    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_audio)

    return wav_buffer.getvalue()
