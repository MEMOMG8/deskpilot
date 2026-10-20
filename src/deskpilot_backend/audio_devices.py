"""Input-device discovery shared by setup, wake word and command capture."""

from dataclasses import dataclass


class AudioDeviceError(RuntimeError):
    """An input device could not be found or queried."""


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    hostapi: str

    @property
    def selection(self) -> dict[str, str]:
        # PortAudio indices can change after a restart or USB reconnect.
        return {"name": self.name, "hostapi": self.hostapi}

    @property
    def label(self) -> str:
        return f"{self.name} ({self.hostapi})"


def list_input_devices(backend=None) -> list[InputDevice]:
    try:
        if backend is None:
            import sounddevice as backend
        hostapis = backend.query_hostapis()
        return [
            InputDevice(index, str(device["name"]), str(hostapis[device["hostapi"]]["name"]))
            for index, device in enumerate(backend.query_devices())
            if device["max_input_channels"] > 0
        ]
    except Exception as error:
        raise AudioDeviceError(
            "Microphones could not be listed. Check Windows audio devices and try Refresh."
        ) from error


def resolve_input_device(selection: dict[str, str] | None, backend=None) -> int | None:
    if selection is None:
        return None  # Follow the Windows/PortAudio default input device.
    matches = [device for device in list_input_devices(backend) if device.selection == selection]
    if len(matches) != 1:
        raise AudioDeviceError(
            "The saved microphone is missing or ambiguous. Open Voice setup and select it again."
        )
    return matches[0].index
