from deskpilot_backend.actions import ProcessLauncher, execute_action
from deskpilot_backend.commands import route_command
from deskpilot_backend.models import (
    ActionExecutionRequest,
    AssistantCommandResponse,
    CommandRequest,
)


def handle_assistant_command(
    command: CommandRequest,
    launcher: ProcessLauncher | None = None,
) -> AssistantCommandResponse:
    routed_command = route_command(command.text)

    if routed_command.action is None:
        return AssistantCommandResponse(
            intent=routed_command.intent,
            status=routed_command.status,
            requires_confirmation=routed_command.requires_confirmation,
            message=routed_command.message,
        )

    execute_action(
        ActionExecutionRequest(
            type=routed_command.action.type,
            target=routed_command.action.target,
        ),
        launcher=launcher,
    )

    return AssistantCommandResponse(
        intent=routed_command.intent,
        status="executed",
        requires_confirmation=routed_command.requires_confirmation,
        action=routed_command.action,
        message="Calculator was recognized and launch was requested.",
    )
