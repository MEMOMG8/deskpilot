import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from deskpilot_backend.models import ActionExecutionRequest, ActionExecutionResponse

SUPPORTED_ACTION_TYPE = "open_app"

ProcessLauncher = Callable[[Sequence[str]], object]


@dataclass(frozen=True)
class ActionDefinition:
    command: tuple[str, ...]
    message: str


ACTION_REGISTRY = {
    (SUPPORTED_ACTION_TYPE, "calculator"): ActionDefinition(
        command=("calc.exe",),
        message="Opening Calculator.",
    ),
    (SUPPORTED_ACTION_TYPE, "notepad"): ActionDefinition(
        command=("notepad.exe",),
        message="Opening Notepad.",
    ),
    (SUPPORTED_ACTION_TYPE, "file_explorer"): ActionDefinition(
        command=("explorer.exe",),
        message="Opening File Explorer.",
    ),
    (SUPPORTED_ACTION_TYPE, "settings"): ActionDefinition(
        command=("explorer.exe", "ms-settings:"),
        message="Opening Windows Settings.",
    ),
    (SUPPORTED_ACTION_TYPE, "browser"): ActionDefinition(
        command=("rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"),
        message="Opening your default browser.",
    ),
}


class UnsupportedActionError(ValueError):
    """Raised when an action is not on DeskPilot's execution allowlist."""


def execute_action(
    action: ActionExecutionRequest,
    launcher: ProcessLauncher | None = None,
) -> ActionExecutionResponse:
    if action.type != SUPPORTED_ACTION_TYPE:
        raise UnsupportedActionError(f"Unsupported action type: {action.type}")

    action_definition = ACTION_REGISTRY.get((action.type, action.target))
    if action_definition is None:
        raise UnsupportedActionError(f"Unsupported action target: {action.target}")

    process_launcher = launcher or subprocess.Popen
    process_launcher(list(action_definition.command))

    return ActionExecutionResponse(
        status="executed",
        executed=True,
        action=action,
        message=action_definition.message,
    )
