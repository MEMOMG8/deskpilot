import ctypes
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from deskpilot_backend.models import ActionExecutionRequest, ActionExecutionResponse

OPEN_APP_ACTION_TYPE = "open_app"
MEDIA_KEY_ACTION_TYPE = "media_key"
KEYEVENTF_KEYUP = 0x0002
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

ProcessLauncher = Callable[[Sequence[str]], object]
KeyEventSender = Callable[[int, int], object]


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    message: str
    command: tuple[str, ...] | None = None
    virtual_key: int | None = None


ACTION_REGISTRY = {
    (OPEN_APP_ACTION_TYPE, "calculator"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("calc.exe",),
        message="Opening Calculator.",
    ),
    (OPEN_APP_ACTION_TYPE, "notepad"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("notepad.exe",),
        message="Opening Notepad.",
    ),
    (OPEN_APP_ACTION_TYPE, "file_explorer"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("explorer.exe",),
        message="Opening File Explorer.",
    ),
    (OPEN_APP_ACTION_TYPE, "settings"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("explorer.exe", "ms-settings:"),
        message="Opening Windows Settings.",
    ),
    (OPEN_APP_ACTION_TYPE, "browser"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"),
        message="Opening your default browser.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "volume_up"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_VOLUME_UP,
        message="Turning volume up.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "volume_down"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_VOLUME_DOWN,
        message="Turning volume down.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "mute"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_VOLUME_MUTE,
        message="Toggling mute.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "play_pause"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_MEDIA_PLAY_PAUSE,
        message="Toggling media playback.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "next_track"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_MEDIA_NEXT_TRACK,
        message="Skipping to the next track.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "previous_track"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_MEDIA_PREV_TRACK,
        message="Going to the previous track.",
    ),
}
SUPPORTED_ACTION_TYPES = {action_type for action_type, _target in ACTION_REGISTRY}


class UnsupportedActionError(ValueError):
    """Raised when an action is not on DeskPilot's execution allowlist."""


def execute_action(
    action: ActionExecutionRequest,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
) -> ActionExecutionResponse:
    if action.type not in SUPPORTED_ACTION_TYPES:
        raise UnsupportedActionError(f"Unsupported action type: {action.type}")

    action_definition = ACTION_REGISTRY.get((action.type, action.target))
    if action_definition is None:
        raise UnsupportedActionError(f"Unsupported action target: {action.target}")

    if action_definition.command is not None:
        process_launcher = launcher or subprocess.Popen
        process_launcher(list(action_definition.command))
    elif action_definition.virtual_key is not None:
        sender = key_event_sender or send_windows_key_event
        sender(action_definition.virtual_key, 0)
        sender(action_definition.virtual_key, KEYEVENTF_KEYUP)

    return ActionExecutionResponse(
        status="executed",
        executed=True,
        action=action,
        message=action_definition.message,
    )


def send_windows_key_event(virtual_key: int, flags: int) -> object:
    if sys.platform != "win32":
        raise UnsupportedActionError("Windows media controls are only supported on Windows.")

    try:
        return ctypes.windll.user32.keybd_event(virtual_key, 0, flags, 0)
    except AttributeError as error:
        raise UnsupportedActionError("Windows media controls are unavailable.") from error
