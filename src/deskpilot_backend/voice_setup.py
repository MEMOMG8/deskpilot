"""Testable first-run services; no UI, cloud requests, or command execution."""

import threading
from collections.abc import Callable

from deskpilot_backend.microphone import (
    DEFAULT_ENERGY_THRESHOLD,
    frame_energy,
    sounddevice_frame_source,
)
from deskpilot_backend.transcription import WhisperTranscriptionService
from deskpilot_backend.wake_word import create_openwakeword_model


class SetupError(RuntimeError):
    """A recoverable setup failure."""


class SetupCancelled(SetupError):
    """The user closed setup while a job was in progress."""


def check_cancelled(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise SetupCancelled("Setup cancelled. No settings were saved.")


def check_microphone(
    selection: dict[str, str] | None,
    progress: Callable[[int], None],
    cancel: threading.Event,
    *,
    frame_source=None,
) -> None:
    """Sample three seconds locally, retaining only an audio-level measurement."""
    check_cancelled(cancel)
    source = frame_source or sounddevice_frame_source
    frames = source(800, 60, device=selection)  # 50 ms at 16 kHz
    audible_frames = 0
    frames_read = 0
    try:
        for frame in frames:
            check_cancelled(cancel)
            energy = frame_energy(frame)
            audible_frames += energy >= DEFAULT_ENERGY_THRESHOLD
            frames_read += 1
            progress(min(100, round(energy / 32768 * 1000)))
            if frames_read == 60:
                break
        check_cancelled(cancel)
        if frames_read < 60 or audible_frames < 3:
            raise SetupError(
                "No clear audio signal detected. Speak closer, check mute/input level, or choose another microphone and retry."
            )
    except SetupError:
        raise
    except Exception as error:
        raise SetupError(
            "Microphone test failed. Check Windows microphone access, reconnect the device, then refresh and retry."
        ) from error
    finally:
        if hasattr(frames, "close"):
            frames.close()


class VoiceModelResources:
    """Load once and reuse the same local models in setup and native listening."""

    def __init__(self, *, wake_factory=None, local_service=None):
        self._wake_factory = wake_factory or create_openwakeword_model
        self.local_service = local_service or WhisperTranscriptionService()
        self._wake_model = None
        self.ready = False
        self._lock = threading.Lock()

    def wake_model(self):
        with self._lock:
            if self._wake_model is None:
                self._wake_model = self._wake_factory()
            return self._wake_model

    def prepare(self, progress: Callable[[str], None], cancel: threading.Event) -> None:
        self.ready = False
        check_cancelled(cancel)
        progress("1 of 2 · Preparing Hey Jarvis. Missing files will download; this may take several minutes.")
        try:
            self.wake_model()
        except Exception as error:
            raise SetupError(
                "Hey Jarvis could not be prepared. Check your connection and free disk space, then retry."
            ) from error
        check_cancelled(cancel)
        progress("2 of 2 · Preparing local English transcription. Missing files will download; this may take several minutes.")
        try:
            self.local_service.prepare()
        except Exception as error:
            raise SetupError(
                "Local transcription could not be prepared. Check your connection and free disk space, then retry."
            ) from error
        check_cancelled(cancel)
        self.ready = True
        progress("Both voice models are ready.")
