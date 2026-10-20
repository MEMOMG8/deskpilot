import json
import sys
import threading
from types import SimpleNamespace

import pytest

from deskpilot_backend.audio_devices import AudioDeviceError, list_input_devices, resolve_input_device
from deskpilot_backend.desktop_voice import NativeVoiceCommandService, apply_native_voice_preferences
from deskpilot_backend.microphone import sounddevice_frame_source
from deskpilot_backend.settings import SettingsStore, SettingsStoreError, default_settings_data, parse_settings
from deskpilot_backend.transcription import WhisperTranscriptionService
from deskpilot_backend.voice_setup import SetupCancelled, SetupError, VoiceModelResources, check_microphone
from deskpilot_backend.wake_word import create_sounddevice_stream


SELECTION = {"name": "USB Microphone", "hostapi": "Windows WASAPI"}


def backend(devices=None):
    return SimpleNamespace(
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        query_devices=lambda: devices or [
            {"name": "Speakers", "hostapi": 0, "max_input_channels": 0},
            {"name": "USB Microphone", "hostapi": 0, "max_input_channels": 1},
        ],
    )


def test_device_discovery_filters_outputs_and_resolves_identity_after_index_changes():
    devices = list_input_devices(backend())
    assert len(devices) == 1
    assert devices[0].selection == SELECTION
    assert resolve_input_device(SELECTION, backend()) == 1
    reordered = backend([{"name": "USB Microphone", "hostapi": 0, "max_input_channels": 1}])
    assert resolve_input_device(SELECTION, reordered) == 0
    assert resolve_input_device(None, reordered) is None


@pytest.mark.parametrize("devices", [
    [{"name": "Other mic", "hostapi": 0, "max_input_channels": 1}],
    [{"name": "USB Microphone", "hostapi": 0, "max_input_channels": 1}] * 2,
])
def test_missing_or_ambiguous_selected_device_never_silently_uses_another(devices):
    with pytest.raises(AudioDeviceError, match="missing or ambiguous"):
        resolve_input_device(SELECTION, backend(devices))


def test_device_query_failure_is_actionable():
    with pytest.raises(AudioDeviceError, match="Refresh"):
        list_input_devices(SimpleNamespace())


def test_wake_word_and_command_capture_use_same_selected_device(monkeypatch):
    audio = backend()
    opened = []

    class Stream:
        def __init__(self, **kwargs):
            opened.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, count):
            return b"\0\0" * count, False

    audio.InputStream = audio.RawInputStream = Stream
    monkeypatch.setitem(sys.modules, "sounddevice", audio)
    create_sounddevice_stream(lambda *args: None, device=SELECTION)
    list(sounddevice_frame_source(800, 1, device=SELECTION))
    assert [call["device"] for call in opened] == [1, 1]
    assert [call["samplerate"] for call in opened] == [16000, 16000]


def test_preferences_apply_selected_device_to_native_command_service():
    settings = parse_settings({**default_settings_data(), "microphone_device": SELECTION})
    service = NativeVoiceCommandService()
    apply_native_voice_preferences(service, settings)
    assert service.microphone_device == SELECTION


def source(amplitude, calls, closed):
    def frames(samples, count, *, device):
        calls.append((samples, count, device))
        try:
            for _ in range(count):
                yield int(amplitude).to_bytes(2, "little", signed=True) * samples
        finally:
            closed.append(True)
    return frames


def test_microphone_test_measures_audio_and_releases_stream():
    calls, closed, levels = [], [], []
    check_microphone(SELECTION, levels.append, threading.Event(), frame_source=source(1000, calls, closed))
    assert calls == [(800, 60, SELECTION)]
    assert len(levels) == 60 and max(levels) > 0
    assert closed == [True]


def test_microphone_test_rejects_silence():
    with pytest.raises(SetupError, match="No clear audio"):
        check_microphone(None, lambda value: None, threading.Event(), frame_source=source(0, [], []))


def test_microphone_cancellation_closes_stream_and_never_passes():
    cancel = threading.Event()
    closed = []
    with pytest.raises(SetupCancelled):
        check_microphone(None, lambda level: cancel.set(), cancel, frame_source=source(500, [], closed))
    assert closed == [True]


def test_microphone_test_device_failure_is_recoverable():
    def broken(*args, **kwargs):
        raise OSError("device disconnected")
        yield
    with pytest.raises(SetupError, match="Windows microphone access"):
        check_microphone(None, lambda level: None, threading.Event(), frame_source=broken)


def test_model_preparation_has_stages_reuses_models_and_does_not_transcribe(monkeypatch):
    calls = []
    local = WhisperTranscriptionService()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(
        WhisperModel=lambda *args, **kwargs: calls.append("whisper") or object()
    ))
    model = object()
    resources = VoiceModelResources(
        wake_factory=lambda: calls.append("wake") or model, local_service=local
    )
    progress = []
    resources.prepare(progress.append, threading.Event())
    resources.prepare(progress.append, threading.Event())
    assert resources.ready and resources.wake_model() is model
    assert calls == ["wake", "whisper"]
    assert "1 of 2" in progress[0] and "2 of 2" in progress[1]


@pytest.mark.parametrize("failed", ["wake", "whisper"])
def test_failed_model_preparation_can_retry_without_marking_ready(failed):
    fail = [True]
    def load(name):
        if name == failed and fail[0]:
            raise OSError("offline")
        return object()
    resources = VoiceModelResources(
        wake_factory=lambda: load("wake"),
        local_service=SimpleNamespace(prepare=lambda: load("whisper")),
    )
    with pytest.raises(SetupError, match="connection"):
        resources.prepare(lambda text: None, threading.Event())
    assert not resources.ready
    fail[0] = False
    resources.prepare(lambda text: None, threading.Event())
    assert resources.ready


def test_cancelled_model_preparation_stops_before_second_stage():
    cancel = threading.Event()
    def wake():
        cancel.set()
        return object()
    resources = VoiceModelResources(
        wake_factory=wake,
        local_service=SimpleNamespace(prepare=lambda: pytest.fail("cancelled")),
    )
    with pytest.raises(SetupCancelled):
        resources.prepare(lambda text: None, cancel)
    assert not resources.ready


def test_setup_save_preserves_other_settings_and_unknown_fields(tmp_path):
    path = tmp_path / "settings.json"
    original = {
        **default_settings_data(), "custom_aliases": {"my calculator": "open calculator"},
        "future_field": {"value": 7}, "command_capture_duration_seconds": 6,
        "wake_listening_on_startup": True, "voice_transcription_provider": "openai",
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    settings = SettingsStore(path).save_voice_setup(SELECTION, use_local=False)
    saved = json.loads(path.read_text())
    assert settings.microphone_device == SELECTION and settings.voice_setup_completed
    assert saved == {**original, "microphone_device": SELECTION, "voice_setup_completed": True}
    SettingsStore(path).save_voice_setup(None, use_local=True)
    saved = json.loads(path.read_text())
    assert saved["voice_transcription_provider"] == saved["voice_command_interpreter_provider"] == "local"
    assert saved["future_field"] == original["future_field"]


@pytest.mark.parametrize("content", ["{broken", "[]", '{"version": 999}'])
def test_setup_save_refuses_to_replace_invalid_settings(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    with pytest.raises(SettingsStoreError):
        SettingsStore(path).save_voice_setup(None, use_local=True)
    assert path.read_text() == content


def test_failed_atomic_save_preserves_original_and_cleans_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    original = json.dumps(default_settings_data())
    path.write_text(original)
    def denied(*args):
        raise PermissionError()
    monkeypatch.setattr("deskpilot_backend.settings.os.replace", denied)
    with pytest.raises(SettingsStoreError, match="not changed"):
        SettingsStore(path).save_voice_setup(None, use_local=True)
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]


def test_old_settings_need_setup_without_changing_existing_file(tmp_path):
    path = tmp_path / "settings.json"
    data = default_settings_data()
    del data["microphone_device"]
    del data["voice_setup_completed"]
    original = json.dumps(data)
    path.write_text(original)
    settings = SettingsStore(path).load_or_create()
    assert settings.microphone_device is None and not settings.voice_setup_completed
    assert not settings.warnings
    assert path.read_text() == original


@pytest.mark.parametrize("selection", [5, "mic", {}, {"name": "mic"}, {"name": "", "hostapi": "API"}])
def test_invalid_microphone_settings_fall_back_and_cannot_be_saved(tmp_path, selection):
    parsed = parse_settings({**default_settings_data(), "microphone_device": selection})
    assert parsed.microphone_device is None and parsed.warnings
    with pytest.raises(SettingsStoreError):
        SettingsStore(tmp_path / "settings.json").save_voice_setup(selection, use_local=True)
