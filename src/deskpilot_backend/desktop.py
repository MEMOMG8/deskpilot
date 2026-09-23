import sys

from deskpilot_backend.desktop_state import DesktopStateController


def main() -> int:
    from PySide6.QtCore import Qt
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

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    state = DesktopStateController()
    overlay = ListeningOverlay()
    icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    tray = QSystemTrayIcon(icon)
    tray.setToolTip("DeskPilot")

    menu = QMenu()
    show_action = QAction("Show listening border")
    hide_action = QAction("Hide border")
    quit_action = QAction("Quit DeskPilot")

    def show_border() -> None:
        state.show_listening_border()
        overlay.show_listening()

    def hide_border() -> None:
        state.hide_border()
        overlay.hide()

    def quit_deskpilot() -> None:
        overlay.hide()
        tray.hide()
        app.quit()

    show_action.triggered.connect(show_border)
    hide_action.triggered.connect(hide_border)
    quit_action.triggered.connect(quit_deskpilot)

    menu.addAction(show_action)
    menu.addAction(hide_action)
    menu.addSeparator()
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
