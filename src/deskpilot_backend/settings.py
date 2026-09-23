import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deskpilot_backend.commands import (
    APPLICATION_COMMANDS,
    CANCEL_COMMANDS,
    DATE_COMMANDS,
    FIXED_SITE_COMMANDS,
    HELP_COMMANDS,
    NOTE_COMMAND_PREFIXES,
    SEARCH_COMMAND_PREFIXES,
    SYSTEM_STATUS_COMMANDS,
    TIME_COMMANDS,
    WORKSPACE_COMMANDS,
    normalize_command_text,
)

SETTINGS_VERSION = 1
DEFAULT_SETTINGS_FILE = Path.home() / "Documents" / "DeskPilot" / "settings.json"
DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS = 4
MIN_COMMAND_CAPTURE_DURATION_SECONDS = 2
MAX_COMMAND_CAPTURE_DURATION_SECONDS = 8
MAX_ALIAS_LENGTH = 80


class SettingsStoreError(RuntimeError):
    """Raised when DeskPilot settings cannot be created safely."""


@dataclass(frozen=True)
class DeskPilotSettings:
    version: int = SETTINGS_VERSION
    command_capture_duration_seconds: int = (
        DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS
    )
    recording_start_cue_enabled: bool = True
    wake_listening_on_startup: bool = False
    custom_aliases: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


SAFE_ALIAS_TARGET_COMMANDS = (
    set(APPLICATION_COMMANDS)
    | set(FIXED_SITE_COMMANDS)
    | set(WORKSPACE_COMMANDS)
    | set(SYSTEM_STATUS_COMMANDS)
    | set(TIME_COMMANDS)
    | set(DATE_COMMANDS)
    | set(CANCEL_COMMANDS)
    | set(HELP_COMMANDS)
    | {"open deskpilot settings"}
)

BUILT_IN_COMMANDS = SAFE_ALIAS_TARGET_COMMANDS | {
    "volume up",
    "turn volume up",
    "volume down",
    "turn volume down",
    "mute",
    "mute volume",
    "play music",
    "pause music",
    "next song",
    "next track",
    "previous song",
    "previous track",
    "take a note",
    "note",
    "read latest note",
    "how many notes do i have",
    "open notes folder",
    "list reminders",
    "what are my reminders",
}


def default_settings_data() -> dict[str, Any]:
    return {
        "version": SETTINGS_VERSION,
        "command_capture_duration_seconds": (
            DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS
        ),
        "recording_start_cue_enabled": True,
        "wake_listening_on_startup": False,
        "custom_aliases": {},
    }


@dataclass(frozen=True)
class SettingsStore:
    settings_file: Path = DEFAULT_SETTINGS_FILE

    def load_or_create(self) -> DeskPilotSettings:
        if not self.settings_file.exists():
            self._write_default_settings()
            return DeskPilotSettings()

        try:
            raw_settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return DeskPilotSettings(
                warnings=(f"DeskPilot settings could not be loaded: {error}",)
            )

        return parse_settings(raw_settings)

    def ensure_settings_file(self) -> Path:
        if not self.settings_file.exists():
            self._write_default_settings()

        return self.settings_file

    def _write_default_settings(self) -> None:
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(
                json.dumps(default_settings_data(), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            raise SettingsStoreError("DeskPilot settings are unavailable.") from error


def parse_settings(raw_settings: object) -> DeskPilotSettings:
    if not isinstance(raw_settings, dict):
        return DeskPilotSettings(
            warnings=("DeskPilot settings must be a JSON object; using defaults.",)
        )

    warnings: list[str] = []

    version = raw_settings.get("version")
    if version != SETTINGS_VERSION:
        return DeskPilotSettings(
            warnings=("DeskPilot settings version is unsupported; using defaults.",)
        )

    command_capture_duration_seconds = _parse_capture_duration(
        raw_settings.get("command_capture_duration_seconds"),
        warnings,
    )
    recording_start_cue_enabled = _parse_bool_setting(
        raw_settings.get("recording_start_cue_enabled"),
        default=True,
        setting_name="recording_start_cue_enabled",
        warnings=warnings,
    )
    wake_listening_on_startup = _parse_bool_setting(
        raw_settings.get("wake_listening_on_startup"),
        default=False,
        setting_name="wake_listening_on_startup",
        warnings=warnings,
    )
    custom_aliases = parse_custom_aliases(
        raw_settings.get("custom_aliases"),
        warnings=warnings,
    )

    return DeskPilotSettings(
        command_capture_duration_seconds=command_capture_duration_seconds,
        recording_start_cue_enabled=recording_start_cue_enabled,
        wake_listening_on_startup=wake_listening_on_startup,
        custom_aliases=custom_aliases,
        warnings=tuple(warnings),
    )


def parse_custom_aliases(
    raw_aliases: object,
    *,
    warnings: list[str] | None = None,
) -> dict[str, str]:
    warning_messages = warnings if warnings is not None else []
    if raw_aliases is None:
        return {}

    if not isinstance(raw_aliases, dict):
        warning_messages.append("custom_aliases must be an object; using none.")
        return {}

    aliases: dict[str, str] = {}
    for alias, target_command in raw_aliases.items():
        if not isinstance(alias, str) or not isinstance(target_command, str):
            warning_messages.append("Custom alias entries must be strings.")
            continue

        normalized_alias = normalize_command_text(alias)
        normalized_target = normalize_command_text(target_command)

        if not _is_valid_alias_phrase(alias, normalized_alias):
            warning_messages.append(f"Custom alias rejected: {alias!r}.")
            continue

        if _is_parameterized_command_phrase(normalized_alias):
            warning_messages.append(
                f"Custom alias cannot be a parameterized command: {alias!r}."
            )
            continue

        if normalized_alias in BUILT_IN_COMMANDS:
            warning_messages.append(
                f"Custom alias duplicates a built-in command: {alias!r}."
            )
            continue

        if normalized_alias in aliases:
            warning_messages.append(
                f"Custom alias collides after normalization: {alias!r}."
            )
            continue

        if normalized_target not in SAFE_ALIAS_TARGET_COMMANDS:
            warning_messages.append(
                f"Custom alias target is not supported: {target_command!r}."
            )
            continue

        aliases[normalized_alias] = normalized_target

    return aliases


def _parse_capture_duration(raw_value: object, warnings: list[str]) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        warnings.append("Invalid command capture duration; using 4 seconds.")
        return DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS

    if (
        raw_value < MIN_COMMAND_CAPTURE_DURATION_SECONDS
        or raw_value > MAX_COMMAND_CAPTURE_DURATION_SECONDS
    ):
        warnings.append("Invalid command capture duration; using 4 seconds.")
        return DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS

    return raw_value


def _parse_bool_setting(
    raw_value: object,
    *,
    default: bool,
    setting_name: str,
    warnings: list[str],
) -> bool:
    if isinstance(raw_value, bool):
        return raw_value

    warnings.append(f"Invalid {setting_name}; using default.")
    return default


def _is_valid_alias_phrase(alias: str, normalized_alias: str) -> bool:
    if not normalized_alias:
        return False

    if len(normalized_alias) > MAX_ALIAS_LENGTH:
        return False

    return not any(_is_control_character(character) for character in alias)


def _is_parameterized_command_phrase(normalized_alias: str) -> bool:
    search_prefixes = tuple(f"{prefix} " for prefix in SEARCH_COMMAND_PREFIXES)
    note_prefixes = tuple(f"{prefix} " for prefix in NOTE_COMMAND_PREFIXES)
    return (
        normalized_alias in SEARCH_COMMAND_PREFIXES
        or normalized_alias.startswith(search_prefixes)
        or normalized_alias.startswith(note_prefixes)
        or normalized_alias.startswith("remind me in ")
    )


def _is_control_character(character: str) -> bool:
    return ord(character) < 32 or ord(character) == 127
