from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Literal

DesktopStateName = Literal["idle", "listening"]


@dataclass
class DesktopStateController:
    state: DesktopStateName = "idle"

    def show_listening_border(self) -> DesktopStateName:
        self.state = "listening"
        return self.state

    def hide_border(self) -> DesktopStateName:
        self.state = "idle"
        return self.state

    @property
    def is_listening(self) -> bool:
        return self.state == "listening"


@dataclass
class WakeWordVisualController:
    state: DesktopStateController
    show_border: Callable[[], None]
    hide_border: Callable[[], None]
    schedule_hide: Callable[[int, Callable[[], None]], None]
    hide_delay_ms: int = 4000

    def activate(self, *, auto_hide: bool = True) -> None:
        self.state.show_listening_border()
        self.show_border()
        if auto_hide:
            self.schedule_hide(self.hide_delay_ms, self.deactivate)

    def deactivate(self) -> None:
        self.state.hide_border()
        self.hide_border()


class NativeWakeWordCommandController:
    def __init__(self) -> None:
        self._wake_word_enabled = False
        self._command_in_progress = False
        self._lock = Lock()

    @property
    def wake_word_enabled(self) -> bool:
        with self._lock:
            return self._wake_word_enabled

    @property
    def command_in_progress(self) -> bool:
        with self._lock:
            return self._command_in_progress

    def enable_wake_word(self) -> None:
        with self._lock:
            self._wake_word_enabled = True

    def disable_wake_word(self) -> None:
        with self._lock:
            self._wake_word_enabled = False

    def begin_command_after_wake_word(self) -> bool:
        with self._lock:
            if not self._wake_word_enabled or self._command_in_progress:
                return False

            self._command_in_progress = True
            return True

    def finish_command(self) -> bool:
        with self._lock:
            self._command_in_progress = False
            return self._wake_word_enabled
