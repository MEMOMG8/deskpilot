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
