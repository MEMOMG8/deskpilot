import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol

WAKE_WORD_MODEL = "hey_jarvis"
WAKE_WORD_LABEL = "Hey Jarvis"
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_SAMPLES = 1280
DETECTION_THRESHOLD = 0.5
LOGGER = logging.getLogger(__name__)

DetectionCallback = Callable[[], None]
ErrorCallback = Callable[[str], None]


class WakeWordModel(Protocol):
    def predict(self, frame: object) -> dict[str, float]:
        ...


class AudioStream(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def close(self) -> None:
        ...


ModelFactory = Callable[[], WakeWordModel]
StreamFactory = Callable[[Callable[[object, int, object, object], None]], AudioStream]


class WakeWordError(RuntimeError):
    """Raised when local wake-word listening cannot start or continue safely."""


class WakeWordService:
    def __init__(
        self,
        on_detected: DetectionCallback,
        *,
        on_error: ErrorCallback | None = None,
        model_factory: ModelFactory | None = None,
        stream_factory: StreamFactory | None = None,
        threshold: float = DETECTION_THRESHOLD,
    ) -> None:
        self._on_detected = on_detected
        self._on_error = on_error
        self._model_factory = model_factory or create_openwakeword_model
        self._stream_factory = stream_factory or create_sounddevice_stream
        self._threshold = threshold
        self._model: WakeWordModel | None = None
        self._stream: AudioStream | None = None
        self._frames: queue.Queue[object] = queue.Queue(maxsize=8)
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return

        try:
            self._model = self._model_factory()
            self._stop_event.clear()
            self._worker = threading.Thread(
                target=self._run_worker,
                name="DeskPilotWakeWord",
                daemon=True,
            )
            self._stream = self._stream_factory(self._audio_callback)
            self._worker.start()
            self._stream.start()
            self._running = True
        except Exception as error:
            LOGGER.exception("Wake-word listening could not start.")
            self.stop()
            raise WakeWordError(
                "Wake-word listening could not start: "
                f"{_summarize_exception(error)}"
            ) from error

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
            self._stream = None

        if self._worker is not None:
            self._worker.join(timeout=1)
            self._worker = None

        self._clear_queued_frames()

    def process_audio_frame(self, frame: object) -> None:
        if self._model is None:
            raise WakeWordError("Wake-word model is not loaded.")

        prediction = self._model.predict(frame)
        if prediction and max(prediction.values()) >= self._threshold:
            self._on_detected()

    def _audio_callback(
        self,
        indata: object,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        if status and self._on_error is not None:
            self._on_error("Wake-word microphone stream reported an audio error.")

        try:
            frame = _copy_mono_frame(indata)
            self._frames.put_nowait(frame)
        except queue.Full:
            return

    def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame = self._frames.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self.process_audio_frame(frame)
            except Exception as error:
                LOGGER.exception("Wake-word detection failed.")
                if self._on_error is not None:
                    self._on_error("Wake-word detection is unavailable.")
                self._stop_event.set()
                self._running = False
                return

    def _clear_queued_frames(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return


def create_openwakeword_model() -> WakeWordModel:
    try:
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        download_models(model_names=[WAKE_WORD_MODEL])
        return Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")
    except Exception as error:
        LOGGER.exception("Wake-word model initialization failed.")
        raise WakeWordError("Wake-word model is unavailable.") from error


def create_sounddevice_stream(
    callback: Callable[[object, int, object, object], None],
) -> AudioStream:
    try:
        import sounddevice

        return sounddevice.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=FRAME_SAMPLES,
            callback=callback,
        )
    except Exception as error:
        LOGGER.exception("Wake-word microphone stream initialization failed.")
        raise WakeWordError("Wake-word microphone stream is unavailable.") from error


def _copy_mono_frame(indata: object) -> object:
    if hasattr(indata, "ndim") and getattr(indata, "ndim") == 2:
        return indata[:, 0].copy()

    if hasattr(indata, "copy"):
        return indata.copy()

    return indata


def _summarize_exception(error: BaseException) -> str:
    root_error = error
    while root_error.__cause__ is not None:
        root_error = root_error.__cause__

    return f"{type(root_error).__name__}: {root_error}"
