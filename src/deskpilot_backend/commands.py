import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from deskpilot_backend.models import CommandAction, CommandResponse

TERMINAL_PUNCTUATION = ".,!?"
HELP_MESSAGE = (
    "Supported commands: open calculator; open notepad; open file explorer; "
    "open explorer; open settings; open browser; what time is it; what's the time; "
    "what is the date; what's today's date; volume up; turn volume up; "
    "volume down; turn volume down; mute; mute volume; play music; pause music; "
    "next song; next track; previous song; previous track; open downloads; "
    "open documents; open desktop; open task manager; battery status; "
    "what is my battery level; memory status; how much memory am I using; "
    "disk space; how much disk space do I have; help; what can you do."
)


@dataclass(frozen=True)
class ApplicationCommand:
    target: str
    display_name: str


APPLICATION_COMMANDS = {
    "open calculator": ApplicationCommand("calculator", "Calculator"),
    "open notepad": ApplicationCommand("notepad", "Notepad"),
    "open file explorer": ApplicationCommand("file_explorer", "File Explorer"),
    "open explorer": ApplicationCommand("file_explorer", "File Explorer"),
    "open settings": ApplicationCommand("settings", "Windows Settings"),
    "open browser": ApplicationCommand("browser", "the default browser"),
}

MEDIA_COMMANDS = {
    "volume up": "volume_up",
    "turn volume up": "volume_up",
    "volume down": "volume_down",
    "turn volume down": "volume_down",
    "mute": "mute",
    "mute volume": "mute",
    "play music": "play_pause",
    "pause music": "play_pause",
    "next song": "next_track",
    "next track": "next_track",
    "previous song": "previous_track",
    "previous track": "previous_track",
}

WORKSPACE_COMMANDS = {
    "open downloads": "downloads",
    "open documents": "documents",
    "open desktop": "desktop",
    "open task manager": "task_manager",
}

SYSTEM_STATUS_COMMANDS = {
    "battery status": "battery",
    "what is my battery level": "battery",
    "memory status": "memory",
    "how much memory am i using": "memory",
    "disk space": "disk",
    "how much disk space do i have": "disk",
}

TIME_COMMANDS = {"what time is it", "what's the time"}
DATE_COMMANDS = {"what is the date", "what's today's date"}
HELP_COMMANDS = {"help", "what can you do"}


def normalize_command_text(text: str) -> str:
    normalized_text = (
        text.strip()
        .casefold()
        .replace("’", "'")
        .rstrip(TERMINAL_PUNCTUATION)
    )
    return re.sub(r"\s+", " ", normalized_text).strip()


def route_command(
    text: str,
    *,
    now_factory: Callable[[], datetime] = datetime.now,
) -> CommandResponse:
    normalized_text = normalize_command_text(text)

    if normalized_text in APPLICATION_COMMANDS:
        command = APPLICATION_COMMANDS[normalized_text]
        return CommandResponse(
            intent="open_app",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(type="open_app", target=command.target),
            message=(
                f"{command.display_name} was recognized, "
                "but DeskPilot will not launch apps yet."
            ),
        )

    if normalized_text in MEDIA_COMMANDS:
        return CommandResponse(
            intent="media_control",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(type="media_key", target=MEDIA_COMMANDS[normalized_text]),
            message="Media control was recognized, but DeskPilot will not send it yet.",
        )

    if normalized_text in WORKSPACE_COMMANDS:
        return CommandResponse(
            intent="workspace_shortcut",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(
                type="workspace_shortcut",
                target=WORKSPACE_COMMANDS[normalized_text],
            ),
            message=(
                "Workspace shortcut was recognized, "
                "but DeskPilot will not open it yet."
            ),
        )

    if normalized_text in SYSTEM_STATUS_COMMANDS:
        return CommandResponse(
            intent="system_status",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(
                type="system_status",
                target=SYSTEM_STATUS_COMMANDS[normalized_text],
            ),
            message=(
                "System status request was recognized, "
                "but DeskPilot will not read it yet."
            ),
        )

    if normalized_text in TIME_COMMANDS:
        return CommandResponse(
            intent="get_time",
            status="completed",
            requires_confirmation=False,
            message=_format_local_time(now_factory()),
        )

    if normalized_text in DATE_COMMANDS:
        return CommandResponse(
            intent="get_date",
            status="completed",
            requires_confirmation=False,
            message=_format_local_date(now_factory()),
        )

    if normalized_text in HELP_COMMANDS:
        return CommandResponse(
            intent="help",
            status="completed",
            requires_confirmation=False,
            message=HELP_MESSAGE,
        )

    return CommandResponse(
        intent="unknown",
        status="not_supported",
        requires_confirmation=False,
        message="That command is not supported yet.",
    )


def _format_local_time(now: datetime) -> str:
    hour = now.strftime("%I").lstrip("0") or "0"
    return f"It is {hour}:{now:%M %p}."


def _format_local_date(now: datetime) -> str:
    return f"Today is {now:%B} {now.day}, {now:%Y}."
