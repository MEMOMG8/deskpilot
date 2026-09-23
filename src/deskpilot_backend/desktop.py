import logging
import sys
import threading

from deskpilot_backend.desktop_state import (
    DesktopStateName,
    DesktopStateController,
    NativeWakeWordCommandController,
    WakeWordVisualController,
)
from deskpilot_backend.desktop_voice import (
    NativeVoiceCommandService,
    apply_native_voice_preferences,
    run_native_voice_handoff,
)
from deskpilot_backend.reminders import ReminderService
from deskpilot_backend.settings import DeskPilotSettings, SettingsStore, SettingsStoreError
from deskpilot_backend.wake_word import WakeWordError, WakeWordService

LOGGER = logging.getLogger(__name__)

OVERLAY_STYLES = {
    "listening": {
        "label": "DeskPilot listening",
        "color": (0, 188, 255),
        "background": "rgba(0, 188, 255, 210)",
        "foreground": "#001b2e",
    },
    "processing": {
        "label": "DeskPilot processing",
        "color": (255, 191, 71),
        "background": "rgba(255, 191, 71, 220)",
        "foreground": "#2b1600",
    },
    "success": {
        "label": "DeskPilot done",
        "color": (62, 201, 123),
        "background": "rgba(62, 201, 123, 220)",
        "foreground": "#052312",
    },
    "error": {
        "label": "DeskPilot needs help",
        "color": (255, 82, 82),
        "background": "rgba(255, 82, 82, 220)",
        "foreground": "#2b0000",
    },
}


def _summarize_exception(error: BaseException) -> str:
    root_error = error
    while root_error.__cause__ is not None:
        root_error = root_error.__cause__

    return f"{type(root_error).__name__}: {root_error}"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QPainter, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QMenu,
        QStyle,
        QSystemTrayIcon,
        QWidget,
    )

    class ListeningOverlay(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("DeskPilot listening")
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
                | Qt.WindowType.WindowTransparentForInput
            )

            self._state_name: DesktopStateName = "listening"
            self.label = QLabel("DeskPilot listening", self)
            self._apply_state_style(self._state_name)
            self._fit_primary_screen()

        def _apply_state_style(self, state_name: DesktopStateName) -> None:
            style = OVERLAY_STYLES.get(state_name, OVERLAY_STYLES["listening"])
            self.label.setText(style["label"])
            self.label.setStyleSheet(
                f"background: {style['background']};"
                f"color: {style['foreground']};"
                "font: 700 13px 'Segoe UI';"
                "padding: 6px 10px;"
                "border-radius: 4px;"
            )

        def _fit_primary_screen(self) -> None:
            screen = QApplication.primaryScreen()
            if screen is None:
                return

            self.setGeometry(screen.geometry())
            self.label.adjustSize()
            self.label.move(16, 16)

        def show_state(self, state_name: DesktopStateName) -> None:
            self._state_name = state_name
            self._apply_state_style(state_name)
            self._fit_primary_screen()
            self.show()
            self.raise_()

        def paintEvent(self, event) -> None:  # noqa: N802
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            color = OVERLAY_STYLES.get(
                self._state_name,
                OVERLAY_STYLES["listening"],
            )["color"]
            pen = QPen(QColor(*color), 4)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))

    class DesktopSignals(QObject):
        wake_word_detected = Signal()
        wake_word_error = Signal(str)
        native_command_processing = Signal()
        native_command_completed = Signal(object)
        native_command_failed = Signal(str)
        reminder_due = Signal(str)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    state = DesktopStateController()
    native_command_state = NativeWakeWordCommandController()
    overlay = ListeningOverlay()
    signals = DesktopSignals()
    settings_store = SettingsStore()
    try:
        deskpilot_settings = settings_store.load_or_create()
    except SettingsStoreError as error:
        LOGGER.warning("DeskPilot settings could not be created: %s", error)
        deskpilot_settings = DeskPilotSettings(warnings=(str(error),))

    visual_controller = WakeWordVisualController(
        state=state,
        show_border=overlay.show_state,
        hide_border=overlay.hide,
        schedule_hide=QTimer.singleShot,
    )
    wake_word_service = WakeWordService(
        on_detected=signals.wake_word_detected.emit,
        on_error=signals.wake_word_error.emit,
    )
    wake_word_lock = threading.Lock()
    icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    tray = QSystemTrayIcon(icon)

    menu = QMenu()
    show_action = QAction("Show listening border")
    hide_action = QAction("Hide border")
    start_wake_action = QAction("Start wake word listening")
    stop_wake_action = QAction("Stop wake word listening")
    quit_action = QAction("Quit DeskPilot")

    def update_tray_state() -> None:
        wake_state = "on" if native_command_state.wake_word_enabled else "off"
        if native_command_state.command_in_progress:
            wake_state = f"{wake_state}, command in progress"

        tray.setToolTip(f"DeskPilot - wake word {wake_state}")
        start_wake_action.setEnabled(
            not native_command_state.wake_word_enabled
            and not native_command_state.command_in_progress
        )
        stop_wake_action.setEnabled(native_command_state.wake_word_enabled)

    def start_wake_word_service() -> None:
        with wake_word_lock:
            wake_word_service.start()

    def stop_wake_word_service() -> None:
        with wake_word_lock:
            wake_word_service.stop()

    def show_border() -> None:
        visual_controller.show_listening()

    def hide_border() -> None:
        state.hide_border()
        overlay.hide()

    def start_wake_word() -> None:
        if native_command_state.command_in_progress:
            tray.showMessage("DeskPilot", "Finish the current command first.")
            return

        native_command_state.enable_wake_word()
        try:
            start_wake_word_service()
        except WakeWordError as error:
            LOGGER.exception("Wake-word listening startup failed.")
            native_command_state.disable_wake_word()
            tray.showMessage("DeskPilot", str(error))
            update_tray_state()
            return

        update_tray_state()
        tray.showMessage("DeskPilot", "Wake-word listening is enabled.")

    def stop_wake_word() -> None:
        native_command_state.disable_wake_word()
        stop_wake_word_service()
        update_tray_state()
        tray.showMessage("DeskPilot", "Wake-word listening is stopped.")

    def on_wake_word_detected() -> None:
        if not native_command_state.begin_command_after_wake_word():
            return

        visual_controller.activate(auto_hide=False)
        update_tray_state()
        tray.showMessage("DeskPilot", "Hey Jarvis detected.")

        worker = threading.Thread(
            target=run_native_command_worker,
            name="DeskPilotNativeVoiceCommand",
            daemon=True,
        )
        worker.start()

    def on_wake_word_error(message: str) -> None:
        stop_wake_word_service()
        native_command_state.disable_wake_word()
        update_tray_state()
        tray.showMessage("DeskPilot", message)

    def run_native_command_worker() -> None:
        try:
            response = run_native_voice_handoff(
                stop_wake_word=stop_wake_word_service,
                run_voice_command=native_voice_service.run,
            )
        except Exception as error:
            LOGGER.exception("Native voice command failed.")
            signals.native_command_failed.emit(
                f"Voice command failed: {_summarize_exception(error)}"
            )
            return

        signals.native_command_completed.emit(response)

    def finish_native_command() -> None:
        should_resume = native_command_state.finish_command()

        if should_resume:
            try:
                start_wake_word_service()
            except WakeWordError as error:
                LOGGER.exception("Wake-word listening resume failed.")
                native_command_state.disable_wake_word()
                tray.showMessage("DeskPilot", str(error))

        update_tray_state()

    def on_native_command_processing() -> None:
        visual_controller.show_processing()

    def on_native_command_completed(response: object) -> None:
        message = getattr(getattr(response, "assistant", None), "message", None)
        assistant_status = getattr(getattr(response, "assistant", None), "status", None)
        if assistant_status == "not_supported":
            visual_controller.show_error(after_hide=finish_native_command)
        else:
            visual_controller.show_success(after_hide=finish_native_command)

        tray.showMessage("DeskPilot", message or "Voice command completed.")

    def on_native_command_failed(message: str) -> None:
        visual_controller.show_error(after_hide=finish_native_command)
        tray.showMessage("DeskPilot", message)

    def on_reminder_due(message: str) -> None:
        tray.showMessage("DeskPilot", message)

    def quit_deskpilot() -> None:
        native_command_state.disable_wake_word()
        stop_wake_word_service()
        reminder_service.stop()
        overlay.hide()
        tray.hide()
        app.quit()

    signals.reminder_due.connect(on_reminder_due)
    reminder_service = ReminderService(notifier=signals.reminder_due.emit)
    native_voice_service = NativeVoiceCommandService(
        reminder_service=reminder_service,
        settings_store=settings_store,
        on_processing_started=signals.native_command_processing.emit,
    )
    start_wake_on_startup = apply_native_voice_preferences(
        native_voice_service,
        deskpilot_settings,
    )

    show_action.triggered.connect(show_border)
    hide_action.triggered.connect(hide_border)
    start_wake_action.triggered.connect(start_wake_word)
    stop_wake_action.triggered.connect(stop_wake_word)
    quit_action.triggered.connect(quit_deskpilot)
    signals.wake_word_detected.connect(on_wake_word_detected)
    signals.wake_word_error.connect(on_wake_word_error)
    signals.native_command_processing.connect(on_native_command_processing)
    signals.native_command_completed.connect(on_native_command_completed)
    signals.native_command_failed.connect(on_native_command_failed)

    menu.addAction(show_action)
    menu.addAction(hide_action)
    menu.addSeparator()
    menu.addAction(start_wake_action)
    menu.addAction(stop_wake_action)
    menu.addSeparator()
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    update_tray_state()
    tray.show()

    for warning in deskpilot_settings.warnings:
        LOGGER.warning("DeskPilot settings warning: %s", warning)
        tray.showMessage("DeskPilot settings", warning)

    if start_wake_on_startup:
        start_wake_word()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
