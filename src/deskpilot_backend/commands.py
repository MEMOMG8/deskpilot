from deskpilot_backend.models import CommandAction, CommandResponse


def route_command(text: str) -> CommandResponse:
    normalized_text = text.strip().casefold()

    if normalized_text == "open calculator":
        return CommandResponse(
            intent="open_app",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(type="open_app", target="calculator"),
            message="Calculator was recognized, but DeskPilot will not launch apps yet.",
        )

    if normalized_text == "help":
        return CommandResponse(
            intent="help",
            status="completed",
            requires_confirmation=False,
            message='Supported commands: "open calculator" and "help".',
        )

    return CommandResponse(
        intent="unknown",
        status="not_supported",
        requires_confirmation=False,
        message="That command is not supported yet.",
    )
