"""Exercise the real tray/setup wiring without recording, downloading, or launching apps."""

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtCore import QTimer

from deskpilot_backend import desktop
from deskpilot_backend.settings import SettingsStore
from deskpilot_backend.audio_devices import InputDevice
from deskpilot_backend.voice_setup import VoiceModelResources
from deskpilot_backend import voice_setup_ui


def test_first_run_setup_saves_then_tray_start_uses_selected_microphone(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    captured = {}
    errors = []

    class ExistingApplication:
        def __new__(cls, args):
            return app
        primaryScreen = staticmethod(app.primaryScreen)

    class Tray:
        def __init__(self, icon):
            pass
        def setContextMenu(self, menu):
            captured["menu"] = menu
        def setToolTip(self, text):
            captured["tooltip"] = text
        def showMessage(self, *args):
            pass
        def show(self):
            pass
        def hide(self):
            pass

    class WakeService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def start(self):
            self.kwargs["model_factory"]()
            self.kwargs["stream_factory"](lambda *args: None)
            captured["started"] = True
        def stop(self):
            pass

    real_dialog = voice_setup_ui.VoiceSetupDialog
    def dialog_factory(*args):
        dialog = real_dialog(
            *args, devices=lambda: [InputDevice(2, "Selected USB", "WASAPI")],
            microphone_check=lambda *args: None,
        )
        captured["dialog"] = dialog
        return dialog

    real_service = desktop.NativeVoiceCommandService
    def service_factory(**kwargs):
        captured["voice"] = real_service(**kwargs)
        return captured["voice"]

    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(QtWidgets, "QApplication", ExistingApplication)
    monkeypatch.setattr(QtWidgets, "QSystemTrayIcon", Tray)
    monkeypatch.setattr(desktop, "SettingsStore", lambda: store)
    monkeypatch.setattr(desktop, "ReminderService", lambda **kwargs: SimpleNamespace(stop=lambda: None))
    monkeypatch.setattr(desktop, "WakeWordService", WakeService)
    monkeypatch.setattr(desktop, "NativeVoiceCommandService", service_factory)
    monkeypatch.setattr(desktop, "create_sounddevice_stream",
                        lambda callback, *, device: captured.update(stream_device=device))
    monkeypatch.setattr(desktop, "VoiceModelResources", lambda: VoiceModelResources(
        wake_factory=lambda: object(), local_service=SimpleNamespace(prepare=lambda: None)
    ))
    monkeypatch.setattr(voice_setup_ui, "VoiceSetupDialog", dialog_factory)

    phase = 0
    deadline = time.monotonic() + 5
    timer = QTimer()

    def tick():
        nonlocal phase
        try:
            assert time.monotonic() < deadline, "Desktop flow timed out"
            dialog = captured.get("dialog")
            if dialog is None or dialog.busy:
                return
            actions = {action.text(): action for action in captured["menu"].actions()}
            if phase == 0:
                assert dialog.isVisible()
                assert not actions["Start wake word listening"].isEnabled()
                dialog.microphone.setCurrentIndex(1)
                dialog.test_microphone()
                phase = 1
            elif phase == 1:
                dialog.prepare_models()
                phase = 2
            elif phase == 2:
                assert dialog.save_button.isEnabled()
                dialog.save_setup()
                assert not captured.get("started"), "Saving must not start the microphone"
                assert actions["Start wake word listening"].isEnabled()
                actions["Start wake word listening"].trigger()
                phase = 3
            elif phase == 3 and captured.get("tooltip") == "DeskPilot - wake word on":
                selected = {"name": "Selected USB", "hostapi": "WASAPI"}
                assert captured["stream_device"] == selected
                assert captured["voice"].microphone_device == selected
                assert store.load_or_create().voice_setup_completed
                assert captured["voice"].voice_transcription_provider == "local"
                phase = 4
                actions["Quit DeskPilot"].trigger()
        except BaseException as error:
            errors.append(error)
            app.quit()

    timer.timeout.connect(tick)
    timer.start(10)
    try:
        assert desktop.main() == 0
    finally:
        timer.stop()
        if "dialog" in captured:
            captured["dialog"].reject()
            captured["dialog"].deleteLater()
        app.processEvents()
    if errors:
        raise errors[0]
    assert phase == 4
