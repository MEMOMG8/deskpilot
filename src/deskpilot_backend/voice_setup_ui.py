"""Native setup dialog. Device checks and model preparation never run on Qt's UI thread."""

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from deskpilot_backend.audio_devices import AudioDeviceError, list_input_devices
from deskpilot_backend.settings import DeskPilotSettings, SettingsStore, SettingsStoreError
from deskpilot_backend.voice_setup import (
    SetupError, VoiceModelResources, check_microphone,
)


class VoiceSetupDialog(QDialog):
    saved = Signal(object)
    busy_changed = Signal()
    _job_done = Signal(str, object, str)
    _progress = Signal(str)
    _level = Signal(int)

    def __init__(
        self, store: SettingsStore, settings: DeskPilotSettings,
        resources: VoiceModelResources, *, devices=list_input_devices,
        microphone_check=check_microphone, parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("DeskPilot · Voice setup")
        self.setMinimumSize(540, 480)
        self.resize(640, 740)
        self.store = store
        self.settings = settings
        self.resources = resources
        self._devices = devices
        self._microphone_check = microphone_check
        self._cancel = threading.Event()
        self._busy = False
        self._mic_ok = False
        self._selection = settings.microphone_device
        self._worker = None

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        title = QLabel("Get started with DeskPilot")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)
        self._text(layout, "Listening is paused during setup. Nothing is recorded until you click Test microphone.")
        self._text(layout, "1. Choose your microphone and speak during the 3-second test.")
        row = QHBoxLayout()
        self.microphone = QComboBox()
        self.microphone.setAccessibleName("Microphone")
        self.refresh_button = QPushButton("Refresh")
        row.addWidget(self.microphone, 1)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.test_button = QPushButton("Test microphone · 3 seconds")
        layout.addWidget(self.test_button)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setFormat("Input level · %p%")
        layout.addWidget(self.level)
        self.mic_status = self._text(layout, "Choose a microphone, then test it.")
        self._text(layout, "The test only measures sound level locally. It does not transcribe, save audio, or run commands.")

        self._text(layout, "2. Prepare voice models. Internet is needed only for missing model files.")
        self.prepare_button = QPushButton("Prepare voice models")
        layout.addWidget(self.prepare_button)
        self.model_status = self._text(
            layout, "Models ready." if resources.ready else "Hey Jarvis and local multilingual transcription have not been checked yet."
        )
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self._text(layout, "Processing mode")
        self.mode = QComboBox()
        self.mode.setAccessibleName("Processing mode")
        for label, value in (("Local · offline", "local"), ("Cloud · online", "openai"), ("Automatic · local first", "auto")):
            self.mode.addItem(label, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.voice_command_interpreter_provider)))
        layout.addWidget(self.mode)
        self.cloud_consent = QCheckBox("Allow sending command audio and text to OpenAI")
        self.cloud_consent.setChecked(settings.cloud_processing_allowed)
        layout.addWidget(self.cloud_consent)
        self._text(
            layout,
            "Local never sends audio or text to a cloud service. Automatic uses local transcription and "
            "interpretation first. Cloud services require an internet connection and your configured "
            "OPENAI_API_KEY, and may incur usage charges. A key alone does not enable cloud access. "
            "Your notes, files and history are not sent. Models are prepared for offline fallback.",
        )
        self._text(layout, "Spoken command language")
        self.language = QComboBox()
        self.language.setAccessibleName("Spoken command language")
        for label, value in (("English", "en"), ("Español", "es"), ("Detect automatically (less reliable for short phrases)", "auto")):
            self.language.addItem(label, value)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.voice_language)))
        layout.addWidget(self.language)
        self._text(layout, "Media phrases: “pause the song”, “make it louder”, “pausa la canción”, "
                   "“sube el volumen”. Wake word stays “Hey Jarvis”. Other exact commands and responses stay in English.")
        self._text(
            layout,
            "3. After saving: open the tray menu → Start wake word listening. Say “Hey Jarvis”, "
            "wait for the cue, then say “open calculator” or “what time is it”.\n"
            "Spotify: “open spotify”, “play music”, “pause music”, “next track”, “previous track”. "
            "No Spotify API connection is needed.\n"
            "Use Stop wake word listening in the tray to stop the microphone.",
        )
        self.status = self._text(layout, "Complete the microphone test and prepare models to save.")
        buttons = QHBoxLayout()
        self.later_button = QPushButton("Later")
        self.save_button = QPushButton("Save setup")
        self.save_button.setDefault(True)
        buttons.addWidget(self.later_button)
        buttons.addStretch()
        buttons.addWidget(self.save_button)
        outer.addLayout(buttons)

        self.microphone.currentIndexChanged.connect(self._device_changed)
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.test_button.clicked.connect(self.test_microphone)
        self.prepare_button.clicked.connect(self.prepare_models)
        self.save_button.clicked.connect(self.save_setup)
        self.later_button.clicked.connect(self.reject)
        self._job_done.connect(self._finished)
        self._progress.connect(self.model_status.setText)
        self._level.connect(self.level.setValue)
        self._update_controls()

    @staticmethod
    def _text(layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(label)
        return label

    @property
    def busy(self) -> bool:
        return self._busy

    def begin(self) -> None:
        """Reopen after Later without saving or automatically starting listening."""
        if self._busy:
            return
        self._cancel.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh_devices()

    def _update_controls(self):
        for widget in (self.microphone, self.refresh_button, self.mode, self.cloud_consent, self.language, self.prepare_button):
            widget.setEnabled(not self._busy)
        self.test_button.setEnabled(not self._busy and self.microphone.count() > 0)
        self.save_button.setEnabled(not self._busy and self._mic_ok and self.resources.ready)
        self.progress.setVisible(self._busy)
        self.later_button.setText("Cancel setup" if self._busy else "Later")

    def _device_changed(self, _index):
        self._selection = self.microphone.currentData()
        self._mic_ok = False
        self.mic_status.setText("Microphone changed. Test it before saving.")
        self.level.setValue(0)
        self._update_controls()

    def _run(self, kind, operation):
        if self._busy:
            return
        self._cancel.clear()
        self._busy = True
        self._update_controls()
        self.busy_changed.emit()

        def work():
            result, message = None, ""
            try:
                result = operation()
            except (SetupError, SettingsStoreError, AudioDeviceError) as error:
                message = str(error)
            except Exception:
                message = "Setup could not complete. Check the device or connection and retry."
            self._job_done.emit(kind, result, message)

        self._worker = threading.Thread(target=work, name=f"DeskPilotSetup-{kind}", daemon=True)
        self._worker.start()

    def refresh_devices(self):
        self._mic_ok = False
        self.status.setText("Looking for microphones…")
        self._run("devices", self._devices)

    def test_microphone(self):
        self._mic_ok = False
        self.mic_status.setText("Speak now for 3 seconds…")
        selection = self._selection
        self._run("microphone", lambda: self._microphone_check(selection, self._level.emit, self._cancel))

    def prepare_models(self):
        self.model_status.setText("Preparing models…")
        self._run("models", lambda: self.resources.prepare(self._progress.emit, self._cancel))

    def _finished(self, kind, result, error):
        self._busy = False
        if self._cancel.is_set():
            self.status.setText("Setup cancelled. No settings were saved.")
        elif error:
            self.status.setText(error)
            if kind == "microphone":
                self.mic_status.setText(error)
            elif kind == "models":
                self.model_status.setText(error)
        elif kind == "devices":
            selection = self._selection
            self.microphone.blockSignals(True)
            self.microphone.clear()
            if result:
                self.microphone.addItem("System default microphone", None)
                for device in result:
                    self.microphone.addItem(device.label, device.selection)
                index = self.microphone.findData(selection)
                self.microphone.setCurrentIndex(max(0, index))
                self._selection = self.microphone.currentData()
                self.status.setText(
                    "Saved microphone unavailable. Choose and test an input."
                    if selection is not None and index < 0 else "Choose an input and click Test microphone."
                )
            else:
                self.status.setText("No input devices found. Connect a microphone and click Refresh.")
            self.microphone.blockSignals(False)
        elif kind == "microphone":
            self._mic_ok = True
            self.mic_status.setText("Audio signal detected. Microphone test passed.")
            self.status.setText("Microphone ready. Prepare models, then save.")
        elif kind == "models":
            self.status.setText("Models ready. Complete the microphone test, then save.")
        self._update_controls()
        self.busy_changed.emit()

    def save_setup(self):
        if self._busy or not self._mic_ok or not self.resources.ready:
            return
        try:
            settings = self.store.save_voice_setup(
                self._selection, mode=self.mode.currentData(),
                cloud_allowed=self.cloud_consent.isChecked(), language=self.language.currentData(),
            )
        except SettingsStoreError as error:
            self.status.setText(str(error))
            return
        self.settings = settings
        self.saved.emit(settings)
        self.accept()

    def reject(self):
        # Downloads cannot be interrupted safely inside the model libraries.
        # Cancel closes the dialog immediately; results are discarded and the
        # desktop keeps listening disabled until the background operation settles.
        self._cancel.set()
        super().reject()
