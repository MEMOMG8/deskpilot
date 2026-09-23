import logging
import sys
import types

import pytest

from deskpilot_backend.wake_word import (
    WAKE_WORD_MODEL,
    WakeWordError,
    WakeWordService,
    create_openwakeword_model,
)


class FakeWakeWordModel:
    def __init__(self, score: float) -> None:
        self.score = score
        self.frames: list[object] = []

    def predict(self, frame: object) -> dict[str, float]:
        self.frames.append(frame)
        return {"hey_jarvis": self.score}


class FakeAudioStream:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def test_wake_word_service_starts_and_stops_stream() -> None:
    stream = FakeAudioStream()
    detections: list[str] = []

    service = WakeWordService(
        on_detected=lambda: detections.append("detected"),
        model_factory=lambda: FakeWakeWordModel(score=0.0),
        stream_factory=lambda callback: stream,
    )

    service.start()

    assert service.is_running is True
    assert stream.started is True

    service.stop()

    assert service.is_running is False
    assert stream.stopped is True
    assert stream.closed is True
    assert detections == []


def test_wake_word_service_calls_detection_callback_when_threshold_is_met() -> None:
    model = FakeWakeWordModel(score=0.8)
    detections: list[str] = []

    service = WakeWordService(
        on_detected=lambda: detections.append("detected"),
        model_factory=lambda: model,
        stream_factory=lambda callback: FakeAudioStream(),
        threshold=0.5,
    )

    service.start()
    service.process_audio_frame("audio frame")
    service.stop()

    assert detections == ["detected"]
    assert model.frames == ["audio frame"]


def test_wake_word_service_ignores_scores_below_threshold() -> None:
    detections: list[str] = []

    service = WakeWordService(
        on_detected=lambda: detections.append("detected"),
        model_factory=lambda: FakeWakeWordModel(score=0.2),
        stream_factory=lambda callback: FakeAudioStream(),
        threshold=0.5,
    )

    service.start()
    service.process_audio_frame("quiet frame")
    service.stop()

    assert detections == []


def test_wake_word_startup_failure_reports_root_cause_and_logs_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_model_factory() -> FakeWakeWordModel:
        raise RuntimeError("model download failed")

    service = WakeWordService(
        on_detected=lambda: None,
        model_factory=failing_model_factory,
        stream_factory=lambda callback: FakeAudioStream(),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(WakeWordError) as error:
            service.start()

    assert str(error.value) == (
        "Wake-word listening could not start: "
        "RuntimeError: model download failed"
    )
    assert "Wake-word listening could not start." in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert "RuntimeError: model download failed" in caplog.text
    assert service.is_running is False


def test_openwakeword_model_download_uses_installed_model_names_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeOpenWakeWordModel:
        def __init__(
            self,
            *,
            wakeword_models: list[str],
            inference_framework: str,
        ) -> None:
            calls["wakeword_models"] = wakeword_models
            calls["inference_framework"] = inference_framework

        def predict(self, frame: object) -> dict[str, float]:
            return {}

    def download_models(*, model_names: list[str]) -> None:
        calls["model_names"] = model_names

    monkeypatch.setitem(
        sys.modules,
        "openwakeword.model",
        types.SimpleNamespace(Model=FakeOpenWakeWordModel),
    )
    monkeypatch.setitem(
        sys.modules,
        "openwakeword.utils",
        types.SimpleNamespace(download_models=download_models),
    )

    model = create_openwakeword_model()

    assert isinstance(model, FakeOpenWakeWordModel)
    assert calls == {
        "model_names": [WAKE_WORD_MODEL],
        "wakeword_models": [WAKE_WORD_MODEL],
        "inference_framework": "onnx",
    }
