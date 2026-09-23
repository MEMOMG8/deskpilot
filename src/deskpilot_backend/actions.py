import subprocess
from collections.abc import Callable, Sequence

from deskpilot_backend.models import ActionExecutionRequest, ActionExecutionResponse

CALCULATOR_COMMAND = ("calc.exe",)
SUPPORTED_ACTION_TYPE = "open_app"
SUPPORTED_ACTION_TARGET = "calculator"

ProcessLauncher = Callable[[Sequence[str]], object]


class UnsupportedActionError(ValueError):
    """Raised when an action is not on DeskPilot's execution allowlist."""


def execute_action(
    action: ActionExecutionRequest,
    launcher: ProcessLauncher | None = None,
) -> ActionExecutionResponse:
    if action.type != SUPPORTED_ACTION_TYPE:
        raise UnsupportedActionError(f"Unsupported action type: {action.type}")

    if action.target != SUPPORTED_ACTION_TARGET:
        raise UnsupportedActionError(f"Unsupported action target: {action.target}")

    process_launcher = launcher or subprocess.Popen
    process_launcher(list(CALCULATOR_COMMAND))

    return ActionExecutionResponse(
        status="executed",
        executed=True,
        action=action,
        message="Calculator launch was requested.",
    )
