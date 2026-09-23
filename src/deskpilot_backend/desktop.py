import logging
import sys

from deskpilot_backend.desktop_state import (
    DesktopStateController,
    WakeWordVisualController,
)
from deskpilot_backend.wake_word import WakeWordError, WakeWordService

LOGGER = logging.getLogger(__name__)


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

            self.label = QLabel("DeskPilot listening", self)
            self.label.setStyleSheet(
                "background: rgba(0, 188, 255, 210);"
                "color: #001b2e;"
                "font: 700 13px 'Segoe UI';"
                "padding: 6px 10px;"
                "border-radius: 4px;"
            )
            self._fit_primary_screen()

        def _fit_primary_screen(self) -> None:
            screen = QApplication.primaryScreen()
            if screen is None:
                return

            self.setGeometry(screen.geometry())
            self.label.adjustSize()
            self.label.move(16, 16)

        def show_listening(self) -> None:
            self._fit_primary_screen()
            self.show()
            self.raise_()

        def paintEvent(self, event) -> None:  # noqa: N802
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            pen = QPen(QColor(0, 188, 255), 4)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))

    class DesktopSignals(QObject):
        wake_word_detected = Signal()
        wake_word_error = Signal(str)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    state = DesktopStateController()
    overlay = ListeningOverlay()
    signals = DesktopSignals()
    visual_controller = WakeWordVisualController(
        state=state,
        show_border=overlay.show_listening,
        hide_border=overlay.hide,
        schedule_hide=QTimer.singleShot,
    )
    wake_word_service = WakeWordService(
        on_detected=signals.wake_word_detected.emit,
        on_error=signals.wake_word_error.emit,
    )
    icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    tray = QSystemTrayIcon(icon)

    menu = QMenu()
    show_action = QAction("Show listening border")
    hide_action = QAction("Hide border")
    start_wake_action = QAction("Start wake word listening")
    stop_wake_action = QAction("Stop wake word listening")
    quit_action = QAction("Quit DeskPilot")

    def update_tray_state() -> None:
        wake_state = "on" if wake_word_service.is_running else "off"
        tray.setToolTip(f"DeskPilot - wake word {wake_state}")
        start_wake_action.setEnabled(not wake_word_service.is_running)
        stop_wake_action.setEnabled(wake_word_service.is_running)

    def show_border() -> None:
        state.show_listening_border()
        overlay.show_listening()

    def hide_border() -> None:
        state.hide_border()
        overlay.hide()

    def start_wake_word() -> None:
        try:
            wake_word_service.start()
        except WakeWordError as error:
            LOGGER.exception("Wake-word listening startup failed.")
            tray.showMessage("DeskPilot", str(error))
            update_tray_state()
            return

        update_tray_state()
        tray.showMessage("DeskPilot", "Wake-word listening is enabled.")

    def stop_wake_word() -> None:
        wake_word_service.stop()
        update_tray_state()
        tray.showMessage("DeskPilot", "Wake-word listening is stopped.")

    def on_wake_word_detected() -> None:
        visual_controller.activate()
        tray.showMessage("DeskPilot", "Hey Jarvis detected.")

    def on_wake_word_error(message: str) -> None:
        wake_word_service.stop()
        update_tray_state()
        tray.showMessage("DeskPilot", message)

    def quit_deskpilot() -> None:
        wake_word_service.stop()
        overlay.hide()
        tray.hide()
        app.quit()

    show_action.triggered.connect(show_border)
    hide_action.triggered.connect(hide_border)
    start_wake_action.triggered.connect(start_wake_word)
    stop_wake_action.triggered.connect(stop_wake_word)
    quit_action.triggered.connect(quit_deskpilot)
    signals.wake_word_detected.connect(on_wake_word_detected)
    signals.wake_word_error.connect(on_wake_word_error)

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

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
