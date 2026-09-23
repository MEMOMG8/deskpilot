import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from deskpilot_backend.models import CommandAction, CommandResponse
from deskpilot_backend.notes import MAX_NOTE_TEXT_LENGTH

TERMINAL_PUNCTUATION = ".,!?"
MAX_SEARCH_QUERY_LENGTH = 120
HELP_MESSAGE = (
    "Supported commands: open calculator; open notepad; open file explorer; "
    "open explorer; open settings; open browser; open google; open youtube; "
    "open github; search web for example query; search google for example query; "
    "search youtube for example query; search github for example query; "
    "what time is it; what's the time; what is the date; what's today's date; "
    "volume up; turn volume up; "
    "volume down; turn volume down; mute; mute volume; play music; pause music; "
    "next song; next track; previous song; previous track; open downloads; "
    "open documents; open desktop; open task manager; battery status; "
    "what is my battery level; memory status; how much memory am I using; "
    "disk space; how much disk space do I have; take a note remember this; "
    "note remember this; read latest note; how many notes do I have; "
    "open notes folder; help; what can you do."
)


class CommandValidationError(ValueError):
    """Raised when a recognized command has an invalid parameter."""


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

FIXED_SITE_COMMANDS = {
    "open google": "google",
    "open youtube": "youtube",
    "open github": "github",
}

SEARCH_COMMAND_PREFIXES = {
    "search web for": "web",
    "search google for": "google",
    "search youtube for": "youtube",
    "search github for": "github",
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

NOTE_COMMANDS = {
    "read latest note": "read_latest",
    "how many notes do i have": "count",
    "open notes folder": "open_folder",
}
NOTE_COMMAND_PREFIXES = ("take a note", "note")

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
    note_response = _route_note_command(text)
    if note_response is not None:
        return note_response

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

    if normalized_text in FIXED_SITE_COMMANDS:
        return CommandResponse(
            intent="open_site",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(
                type="open_url",
                target=FIXED_SITE_COMMANDS[normalized_text],
            ),
            message="Website was recognized, but DeskPilot will not open it yet.",
        )

    search_response = _route_search_command(normalized_text, text)
    if search_response is not None:
        return search_response

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

    if normalized_text in NOTE_COMMANDS:
        return CommandResponse(
            intent="notes",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(type="note", target=NOTE_COMMANDS[normalized_text]),
            message="Notes command was recognized, but DeskPilot will not run it yet.",
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


def _route_note_command(text: str) -> CommandResponse | None:
    stripped_text = text.strip()
    casefolded_text = stripped_text.casefold()

    for prefix in NOTE_COMMAND_PREFIXES:
        if casefolded_text == prefix:
            raise CommandValidationError("Note text must not be empty.")

        prefix_with_space = f"{prefix} "
        if casefolded_text.startswith(prefix_with_space):
            raw_note_text = stripped_text[len(prefix_with_space) :]
            note_text = _normalize_note_text(raw_note_text)
            _validate_note_text(raw_note_text, note_text)
            return CommandResponse(
                intent="notes",
                status="planned",
                requires_confirmation=False,
                action=CommandAction(type="note", target="create", query=note_text),
                message="Note was recognized, but DeskPilot will not save it yet.",
            )

    return None


def _normalize_note_text(note_text: str) -> str:
    return re.sub(r"\s+", " ", note_text.strip())


def _validate_note_text(raw_note_text: str, normalized_note_text: str) -> None:
    if not normalized_note_text:
        raise CommandValidationError("Note text must not be empty.")

    if len(normalized_note_text) > MAX_NOTE_TEXT_LENGTH:
        raise CommandValidationError("Note text is too long.")

    if any(_is_control_character(character) for character in raw_note_text):
        raise CommandValidationError(
            "Note text contains unsupported control characters."
        )


def _route_search_command(
    normalized_text: str,
    original_text: str,
) -> CommandResponse | None:
    for prefix, target in SEARCH_COMMAND_PREFIXES.items():
        if normalized_text == prefix:
            raise CommandValidationError("Search query must not be empty.")

        prefix_with_space = f"{prefix} "
        if normalized_text.startswith(prefix_with_space):
            query = normalized_text.removeprefix(prefix_with_space)
            _validate_search_query(query, original_text)
            return CommandResponse(
                intent="web_search",
                status="planned",
                requires_confirmation=False,
                action=CommandAction(type="web_search", target=target, query=query),
                message="Search was recognized, but DeskPilot will not open it yet.",
            )

    return None


def _validate_search_query(query: str, original_text: str) -> None:
    if not query.strip():
        raise CommandValidationError("Search query must not be empty.")

    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise CommandValidationError("Search query is too long.")

    if any(_is_control_character(character) for character in original_text):
        raise CommandValidationError(
            "Search query contains unsupported control characters."
        )


def _is_control_character(character: str) -> bool:
    return ord(character) < 32 or ord(character) == 127


def _format_local_time(now: datetime) -> str:
    hour = now.strftime("%I").lstrip("0") or "0"
    return f"It is {hour}:{now:%M %p}."


def _format_local_date(now: datetime) -> str:
    return f"Today is {now:%B} {now.day}, {now:%Y}."
