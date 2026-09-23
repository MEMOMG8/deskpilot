from collections.abc import Callable
from dataclasses import dataclass
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

    def activate(self) -> None:
        self.state.show_listening_border()
        self.show_border()
        self.schedule_hide(self.hide_delay_ms, self.deactivate)

    def deactivate(self) -> None:
        self.state.hide_border()
        self.hide_border()
