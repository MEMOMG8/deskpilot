import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from deskpilot_backend.audio_devices import InputDevice
from deskpilot_backend.settings import DeskPilotSettings, SettingsStore
from deskpilot_backend.voice_setup import SetupError, VoiceModelResources
from deskpilot_backend.voice_setup_ui import VoiceSetupDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(app, dialog):
    deadline = time.monotonic() + 3
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not dialog.busy


@pytest.fixture
def dialog(app, tmp_path):
    resources = VoiceModelResources(
        wake_factory=lambda: object(), local_service=SimpleNamespace(prepare=lambda: None)
    )
    dialog = VoiceSetupDialog(
        SettingsStore(tmp_path / "settings.json"), DeskPilotSettings(), resources,
        devices=lambda: [InputDevice(3, "USB Mic", "WASAPI")],
        microphone_check=lambda *args: None,
    )
    dialog.begin()
    settle(app, dialog)
    yield dialog
    dialog.reject()
    settle(app, dialog)
    dialog.deleteLater()
    app.processEvents()


def test_save_requires_successful_microphone_and_models(app, dialog):
    assert not dialog.save_button.isEnabled()
    dialog.test_button.click()
    settle(app, dialog)
    assert not dialog.save_button.isEnabled()
    dialog.prepare_button.click()
    settle(app, dialog)
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    settings = dialog.store.load_or_create()
    assert settings.voice_setup_completed
    assert settings.voice_transcription_provider == "local"
    assert not dialog.isVisible()


def test_changing_microphone_invalidates_prior_test(app, dialog):
    dialog.test_microphone()
    settle(app, dialog)
    dialog.prepare_models()
    settle(app, dialog)
    dialog.microphone.setCurrentIndex(1)
    assert not dialog.save_button.isEnabled()
    dialog.test_microphone()
    settle(app, dialog)
    dialog.save_setup()
    assert dialog.store.load_or_create().microphone_device == {"name": "USB Mic", "hostapi": "WASAPI"}


def test_silent_microphone_does_not_enable_save_and_can_retry(app, dialog):
    def silence(*args):
        raise SetupError("No clear audio signal detected. Retry.")
    dialog._microphone_check = silence
    dialog.test_microphone()
    settle(app, dialog)
    assert "No clear audio" in dialog.mic_status.text()
    assert not dialog.save_button.isEnabled()
    dialog._microphone_check = lambda *args: None
    dialog.test_microphone()
    settle(app, dialog)
    assert "passed" in dialog.mic_status.text()


def test_no_devices_gives_refresh_guidance_and_blocks_test(app, dialog):
    dialog._devices = lambda: []
    dialog.refresh_devices()
    settle(app, dialog)
    assert "No input devices" in dialog.status.text()
    assert not dialog.test_button.isEnabled()
    assert not dialog.save_button.isEnabled()


def test_setup_cancel_does_not_write_settings_or_start_listening(dialog):
    dialog.reject()
    assert not dialog.store.settings_file.exists()


def test_model_error_is_visible_and_retryable(app, dialog):
    def offline():
        raise OSError("offline")
    dialog.resources._wake_factory = offline
    dialog.prepare_models()
    settle(app, dialog)
    assert "connection" in dialog.model_status.text()
    assert not dialog.resources.ready
    assert dialog.prepare_button.isEnabled()
    dialog.resources._wake_factory = lambda: object()
    dialog.prepare_models()
    settle(app, dialog)
    assert dialog.resources.ready


def test_long_model_job_keeps_ui_responsive_and_cancel_discards_completion(app, dialog):
    release = threading.Event()
    entered = threading.Event()
    def load():
        entered.set()
        release.wait(2)
        return object()
    dialog.resources._wake_factory = load
    dialog.prepare_models()
    try:
        assert entered.wait(1)
        app.processEvents()
        assert dialog.busy
        assert dialog.later_button.isEnabled()
        assert not dialog.save_button.isEnabled()
        dialog.later_button.click()
        assert not dialog.isVisible()
        assert not dialog.store.settings_file.exists()
    finally:
        release.set()
    settle(app, dialog)
    assert not dialog.resources.ready
    assert not dialog.store.settings_file.exists()


def test_save_failure_keeps_dialog_open_and_original_file(app, dialog):
    dialog.store.settings_file.write_text("{broken")
    dialog.test_microphone()
    settle(app, dialog)
    dialog.prepare_models()
    settle(app, dialog)
    dialog.save_setup()
    assert dialog.isVisible()
    assert "could not be saved" in dialog.status.text()
    assert dialog.store.settings_file.read_text() == "{broken"


def test_existing_cloud_preference_is_not_silently_changed(app, tmp_path):
    dialog = VoiceSetupDialog(
        SettingsStore(tmp_path / "settings.json"),
        DeskPilotSettings(voice_transcription_provider="openai"),
        VoiceModelResources(),
    )
    assert not dialog.local_mode.isChecked()
    dialog.deleteLater()
    app.processEvents()
