import json
import os
import tempfile
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
    SPOTIFY_COMMANDS,
    SYSTEM_STATUS_COMMANDS,
    TIME_COMMANDS,
    WORKSPACE_COMMANDS,
    normalize_command_text,
)
from deskpilot_backend.command_interpreter import (
    DEFAULT_COMMAND_INTERPRETER_PROVIDER,
    InterpreterProvider,
)
from deskpilot_backend.transcription import (
    DEFAULT_TRANSCRIPTION_PROVIDER,
    TranscriptionProvider,
)

SETTINGS_VERSION = 1
DEFAULT_SETTINGS_FILE = Path.home() / "Documents" / "DeskPilot" / "settings.json"
DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS = 4
MIN_COMMAND_CAPTURE_DURATION_SECONDS = 2
MAX_COMMAND_CAPTURE_DURATION_SECONDS = 8
MAX_ALIAS_LENGTH = 80
ALLOWED_TRANSCRIPTION_PROVIDERS = {"auto", "local", "openai"}
ALLOWED_COMMAND_INTERPRETER_PROVIDERS = {"auto", "local", "openai"}
DEFAULT_MUSIC_APP = "spotify"
ALLOWED_DEFAULT_MUSIC_APPS = {DEFAULT_MUSIC_APP}


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
    voice_transcription_provider: TranscriptionProvider = (
        DEFAULT_TRANSCRIPTION_PROVIDER
    )
    voice_command_interpreter_provider: InterpreterProvider = (
        DEFAULT_COMMAND_INTERPRETER_PROVIDER
    )
    default_music_app: str = DEFAULT_MUSIC_APP
    custom_aliases: dict[str, str] = field(default_factory=dict)
    microphone_device: dict[str, str] | None = None
    voice_setup_completed: bool = False
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

BUILT_IN_COMMANDS = SAFE_ALIAS_TARGET_COMMANDS | set(SPOTIFY_COMMANDS) | {
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
    "set spotify volume to",
}


def default_settings_data() -> dict[str, Any]:
    return {
        "version": SETTINGS_VERSION,
        "command_capture_duration_seconds": (
            DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS
        ),
        "recording_start_cue_enabled": True,
        "wake_listening_on_startup": False,
        "voice_transcription_provider": DEFAULT_TRANSCRIPTION_PROVIDER,
        "voice_command_interpreter_provider": DEFAULT_COMMAND_INTERPRETER_PROVIDER,
        "default_music_app": DEFAULT_MUSIC_APP,
        "custom_aliases": {},
        "microphone_device": None,
        "voice_setup_completed": False,
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

    def save_voice_setup(
        self, microphone_device: dict[str, str] | None, *, use_local: bool
    ) -> DeskPilotSettings:
        """Update only setup-owned fields, preserving existing user preferences."""
        warnings: list[str] = []
        selected = _parse_microphone_device(microphone_device, warnings)
        if warnings:
            raise SettingsStoreError("Choose a valid microphone before saving.")
        temp_path: str | None = None
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            if self.settings_file.exists():
                raw = json.loads(self.settings_file.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("version") != SETTINGS_VERSION:
                    raise SettingsStoreError(
                        "Existing settings have an unsupported format. Your file was not changed."
                    )
            else:
                raw = default_settings_data()
            raw.update(microphone_device=selected, voice_setup_completed=True)
            if use_local:
                raw.update(voice_transcription_provider="local", voice_command_interpreter_provider="local")
            # Write beside the destination, then replace atomically. Invalid JSON
            # is never silently replaced with defaults by this explicit save.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.settings_file.parent,
                prefix=".voice-setup-", suffix=".tmp", delete=False,
            ) as target:
                temp_path = target.name
                target.write(json.dumps(raw, indent=2) + "\n")
            os.replace(temp_path, self.settings_file)
            return parse_settings(raw)
        except (OSError, ValueError) as error:
            raise SettingsStoreError(
                "Voice setup could not be saved. Check settings.json and folder permissions; your existing file was not changed."
            ) from error
        finally:
            if temp_path is not None and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

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
    voice_transcription_provider = _parse_transcription_provider(
        raw_settings.get(
            "voice_transcription_provider",
            DEFAULT_TRANSCRIPTION_PROVIDER,
        ),
        warnings,
    )
    voice_command_interpreter_provider = _parse_command_interpreter_provider(
        raw_settings.get(
            "voice_command_interpreter_provider",
            DEFAULT_COMMAND_INTERPRETER_PROVIDER,
        ),
        warnings,
    )
    default_music_app = _parse_default_music_app(
        raw_settings.get("default_music_app", DEFAULT_MUSIC_APP),
        warnings,
    )
    custom_aliases = parse_custom_aliases(
        raw_settings.get("custom_aliases"),
        warnings=warnings,
    )
    microphone_device = _parse_microphone_device(raw_settings.get("microphone_device"), warnings)
    voice_setup_completed = _parse_bool_setting(
        raw_settings.get("voice_setup_completed", False),
        default=False,
        setting_name="voice_setup_completed",
        warnings=warnings,
    )

    return DeskPilotSettings(
        command_capture_duration_seconds=command_capture_duration_seconds,
        recording_start_cue_enabled=recording_start_cue_enabled,
        wake_listening_on_startup=wake_listening_on_startup,
        voice_transcription_provider=voice_transcription_provider,
        voice_command_interpreter_provider=voice_command_interpreter_provider,
        default_music_app=default_music_app,
        custom_aliases=custom_aliases,
        microphone_device=microphone_device,
        voice_setup_completed=voice_setup_completed,
        warnings=tuple(warnings),
    )


def _parse_microphone_device(raw: object, warnings: list[str]) -> dict[str, str] | None:
    if raw is None:
        return None
    if (
        isinstance(raw, dict)
        and set(raw) == {"name", "hostapi"}
        and all(isinstance(value, str) and 0 < len(value.strip()) <= 512 for value in raw.values())
    ):
        return dict(raw)
    warnings.append("Invalid microphone selection; using the default input device.")
    return None


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


def _parse_transcription_provider(
    raw_value: object,
    warnings: list[str],
) -> TranscriptionProvider:
    if isinstance(raw_value, str) and raw_value in ALLOWED_TRANSCRIPTION_PROVIDERS:
        return raw_value

    warnings.append("Invalid voice transcription provider; using auto.")
    return DEFAULT_TRANSCRIPTION_PROVIDER


def _parse_command_interpreter_provider(
    raw_value: object,
    warnings: list[str],
) -> InterpreterProvider:
    if isinstance(raw_value, str) and raw_value in ALLOWED_COMMAND_INTERPRETER_PROVIDERS:
        return raw_value

    warnings.append("Invalid voice command interpreter provider; using auto.")
    return DEFAULT_COMMAND_INTERPRETER_PROVIDER


def _parse_default_music_app(raw_value: object, warnings: list[str]) -> str:
    if isinstance(raw_value, str) and raw_value in ALLOWED_DEFAULT_MUSIC_APPS:
        return raw_value

    warnings.append("Invalid default music app; using spotify.")
    return DEFAULT_MUSIC_APP


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
        or normalized_alias.startswith("set spotify volume to ")
    )


def _is_control_character(character: str) -> bool:
    return ord(character) < 32 or ord(character) == 127
