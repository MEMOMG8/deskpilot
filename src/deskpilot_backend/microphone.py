import io
import wave
from collections.abc import Callable

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
DTYPE = "int16"

AudioRecorder = Callable[[int], bytes]


class MicrophoneError(RuntimeError):
    """Raised when local microphone recording cannot complete safely."""


def record_microphone_wav(duration_seconds: int) -> bytes:
    try:
        return _record_microphone_wav(duration_seconds)
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


def encode_wav(pcm_audio: bytes) -> bytes:
    wav_buffer = io.BytesIO()

    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_audio)

    return wav_buffer.getvalue()
