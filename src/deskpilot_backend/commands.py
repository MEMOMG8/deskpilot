import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from deskpilot_backend.models import CommandAction, CommandResponse
from deskpilot_backend.notes import MAX_NOTE_TEXT_LENGTH
from deskpilot_backend.reminders import MAX_REMINDER_TEXT_LENGTH

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
    "open notes folder; remind me in one minute to stretch; "
    "remind me in 10 minutes to stretch; list reminders; "
    "what are my reminders; open deskpilot settings; "
    "cancel; never mind; help; what can you do."
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
DESKPILOT_SETTINGS_COMMANDS = {"open deskpilot settings"}
REMINDER_COMMANDS = {"list reminders", "what are my reminders"}
REMINDER_COMMAND_PATTERN = re.compile(
    r"^remind\s+me\s+in\s+(.+?)\s+minutes?\s+to(?:\s+|$)",
    re.IGNORECASE,
)
REMINDER_USAGE_MESSAGE = "Use: remind me in <N> minutes to <text>."
MIN_REMINDER_MINUTES = 1
MAX_REMINDER_MINUTES = 1440

NUMBER_UNITS = {
    "zero": 0,
    "a": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
NUMBER_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
NUMBER_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

TIME_COMMANDS = {"what time is it", "what's the time"}
DATE_COMMANDS = {"what is the date", "what's today's date"}
CANCEL_COMMANDS = {"cancel", "never mind"}
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
    custom_aliases: Mapping[str, str] | None = None,
) -> CommandResponse:
    normalized_text = normalize_command_text(text)
    if custom_aliases and normalized_text in custom_aliases:
        return route_command(
            custom_aliases[normalized_text],
            now_factory=now_factory,
        )

    note_response = _route_note_command(text)
    if note_response is not None:
        return note_response

    reminder_response = _route_reminder_command(text)
    if reminder_response is not None:
        return reminder_response

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

    if normalized_text in DESKPILOT_SETTINGS_COMMANDS:
        return CommandResponse(
            intent="settings",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(type="deskpilot_settings", target="open_file"),
            message=(
                "DeskPilot settings were recognized, "
                "but DeskPilot will not open them yet."
            ),
        )

    if normalized_text in REMINDER_COMMANDS:
        return CommandResponse(
            intent="reminders",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(type="reminder", target="list"),
            message=(
                "Reminder command was recognized, "
                "but DeskPilot will not run it yet."
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

    if normalized_text in CANCEL_COMMANDS:
        return CommandResponse(
            intent="cancel",
            status="completed",
            requires_confirmation=False,
            message="Cancelled.",
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


def _route_reminder_command(text: str) -> CommandResponse | None:
    stripped_text = text.strip()

    if re.match(r"^remind\s+me\s+in\s+", stripped_text, re.IGNORECASE):
        match = REMINDER_COMMAND_PATTERN.match(stripped_text)
        if match is None:
            raise CommandValidationError(REMINDER_USAGE_MESSAGE)

        minutes = _parse_reminder_minutes(match.group(1))
        raw_reminder_text = stripped_text[match.end() :]
        reminder_text = _normalize_note_text(raw_reminder_text)
        _validate_reminder_text(raw_reminder_text, reminder_text)
        return CommandResponse(
            intent="reminders",
            status="planned",
            requires_confirmation=False,
            action=CommandAction(
                type="reminder",
                target="create",
                query=reminder_text,
                minutes=minutes,
            ),
            message="Reminder was recognized, but DeskPilot will not schedule it yet.",
        )

    return None


def _parse_reminder_minutes(value: str) -> int:
    normalized_value = re.sub(r"\s+", " ", value.strip().casefold())
    if not normalized_value:
        raise CommandValidationError(REMINDER_USAGE_MESSAGE)

    if normalized_value.isdecimal():
        minutes = int(normalized_value)
    else:
        minutes = _parse_english_number(normalized_value)
        if minutes is None:
            raise CommandValidationError(REMINDER_USAGE_MESSAGE)

    if minutes < MIN_REMINDER_MINUTES or minutes > MAX_REMINDER_MINUTES:
        raise CommandValidationError("Reminder minutes must be between 1 and 1440.")

    return minutes


def _parse_english_number(value: str) -> int | None:
    words = value.split()
    if not words or words.count("thousand") > 1:
        return None

    if "thousand" not in words:
        return _parse_under_thousand(words)

    thousand_index = words.index("thousand")
    multiplier_words = words[:thousand_index]
    remainder_words = words[thousand_index + 1 :]
    multiplier = _parse_single_digit(multiplier_words)
    if multiplier is None or multiplier == 0:
        return None

    if not remainder_words:
        return multiplier * 1000

    remainder = _parse_under_thousand(remainder_words)
    if remainder is None:
        return None

    return multiplier * 1000 + remainder


def _parse_under_thousand(words: list[str]) -> int | None:
    if not words:
        return None

    if "thousand" in words:
        return None

    if "hundred" not in words:
        return _parse_under_hundred(words)

    if words.count("hundred") > 1:
        return None

    hundred_index = words.index("hundred")
    multiplier = _parse_single_digit(words[:hundred_index])
    if multiplier is None or multiplier == 0:
        return None

    remainder_words = words[hundred_index + 1 :]
    if remainder_words[:1] == ["and"]:
        remainder_words = remainder_words[1:]

    if not remainder_words:
        return multiplier * 100

    remainder = _parse_under_hundred(remainder_words)
    if remainder is None:
        return None

    return multiplier * 100 + remainder


def _parse_under_hundred(words: list[str]) -> int | None:
    if len(words) == 1:
        word = words[0]
        if word in NUMBER_UNITS:
            return NUMBER_UNITS[word]
        if word in NUMBER_TEENS:
            return NUMBER_TEENS[word]
        if word in NUMBER_TENS:
            return NUMBER_TENS[word]
        return None

    if len(words) == 2 and words[0] in NUMBER_TENS and words[1] in NUMBER_UNITS:
        unit = NUMBER_UNITS[words[1]]
        if unit == 0:
            return None
        return NUMBER_TENS[words[0]] + unit

    return None


def _parse_single_digit(words: list[str]) -> int | None:
    if len(words) != 1:
        return None

    value = NUMBER_UNITS.get(words[0])
    if value is None or value > 9:
        return None

    return value


def _validate_reminder_text(
    raw_reminder_text: str,
    normalized_reminder_text: str,
) -> None:
    if not normalized_reminder_text:
        raise CommandValidationError("Reminder text must not be empty.")

    if len(normalized_reminder_text) > MAX_REMINDER_TEXT_LENGTH:
        raise CommandValidationError("Reminder text is too long.")

    if any(_is_control_character(character) for character in raw_reminder_text):
        raise CommandValidationError(
            "Reminder text contains unsupported control characters."
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
