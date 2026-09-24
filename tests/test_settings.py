import json

from deskpilot_backend.commands import route_command
from deskpilot_backend.desktop_voice import (
    NativeVoiceCommandService,
    apply_native_voice_preferences,
)
from deskpilot_backend.settings import (
    DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS,
    DEFAULT_TRANSCRIPTION_PROVIDER,
    DeskPilotSettings,
    SettingsStore,
    default_settings_data,
    parse_settings,
)


def test_settings_file_is_created_with_safe_defaults_on_first_run(tmp_path) -> None:
    settings_file = tmp_path / "DeskPilot" / "settings.json"
    store = SettingsStore(settings_file)

    settings = store.load_or_create()

    assert settings == DeskPilotSettings()
    assert json.loads(settings_file.read_text(encoding="utf-8")) == (
        default_settings_data()
    )


def test_invalid_capture_duration_falls_back_to_safe_default() -> None:
    settings = parse_settings(
        {
            "version": 1,
            "command_capture_duration_seconds": 99,
            "recording_start_cue_enabled": True,
            "wake_listening_on_startup": False,
            "custom_aliases": {},
        }
    )

    assert settings.command_capture_duration_seconds == (
        DEFAULT_COMMAND_CAPTURE_DURATION_SECONDS
    )
    assert settings.warnings


def test_invalid_voice_transcription_provider_falls_back_to_auto() -> None:
    settings = parse_settings(
        {
            "version": 1,
            "command_capture_duration_seconds": 4,
            "recording_start_cue_enabled": True,
            "wake_listening_on_startup": False,
            "voice_transcription_provider": "cloudy",
            "custom_aliases": {},
        }
    )

    assert settings.voice_transcription_provider == DEFAULT_TRANSCRIPTION_PROVIDER
    assert settings.warnings == ("Invalid voice transcription provider; using auto.",)


def test_malformed_existing_settings_uses_defaults_without_rewriting(tmp_path) -> None:
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{not json", encoding="utf-8")
    store = SettingsStore(settings_file)

    settings = store.load_or_create()

    assert settings.command_capture_duration_seconds == 4
    assert settings.custom_aliases == {}
    assert settings.warnings
    assert settings_file.read_text(encoding="utf-8") == "{not json"


def test_valid_custom_alias_routes_to_existing_fixed_command() -> None:
    settings = parse_settings(
        {
            "version": 1,
            "command_capture_duration_seconds": 4,
            "recording_start_cue_enabled": True,
            "wake_listening_on_startup": False,
            "custom_aliases": {"open my projects": "open github"},
        }
    )

    response = route_command(
        "  OPEN   MY   PROJECTS!  ",
        custom_aliases=settings.custom_aliases,
    )

    assert settings.warnings == ()
    assert response.intent == "open_site"
    assert response.action is not None
    assert response.action.type == "open_url"
    assert response.action.target == "github"


def test_custom_alias_rejects_builtin_collision_after_normalization() -> None:
    settings = parse_settings(
        {
            "version": 1,
            "command_capture_duration_seconds": 4,
            "recording_start_cue_enabled": True,
            "wake_listening_on_startup": False,
            "custom_aliases": {
                " Open   Github! ": "open google",
                "open github": "open youtube",
            },
        }
    )

    assert settings.custom_aliases == {}
    assert len(settings.warnings) == 2


def test_custom_alias_rejects_alias_collision_after_normalization() -> None:
    settings = parse_settings(
        {
            "version": 1,
            "command_capture_duration_seconds": 4,
            "recording_start_cue_enabled": True,
            "wake_listening_on_startup": False,
            "custom_aliases": {
                "open my projects": "open github",
                " OPEN   MY   PROJECTS! ": "open google",
            },
        }
    )

    assert settings.custom_aliases == {"open my projects": "open github"}
    assert len(settings.warnings) == 1


def test_custom_alias_rejects_unsupported_targets_and_parameterized_aliases() -> None:
    settings = parse_settings(
        {
            "version": 1,
            "command_capture_duration_seconds": 4,
            "recording_start_cue_enabled": True,
            "wake_listening_on_startup": False,
            "custom_aliases": {
                "open music": "play music",
                "find cats": "search google for cats",
                "search google for": "open github",
                "search google for cats": "open github",
                "take a note cats": "open github",
            },
        }
    )

    assert settings.custom_aliases == {}
    assert len(settings.warnings) == 5


def test_native_startup_preferences_configure_voice_service() -> None:
    service = NativeVoiceCommandService(cue_player=lambda: None)
    enabled_cue_calls: list[str] = []
    disabled_cue_calls: list[str] = []
    settings = DeskPilotSettings(
        command_capture_duration_seconds=6,
        recording_start_cue_enabled=False,
        wake_listening_on_startup=True,
        voice_transcription_provider="openai",
        custom_aliases={"open my projects": "open github"},
    )

    should_start_wake = apply_native_voice_preferences(
        service,
        settings,
        enabled_cue_player=lambda: enabled_cue_calls.append("enabled"),
        disabled_cue_player=lambda: disabled_cue_calls.append("disabled"),
    )

    assert should_start_wake is True
    assert service.capture_duration_seconds == 6
    assert service.voice_transcription_provider == "openai"
    assert service.custom_aliases == {"open my projects": "open github"}

    service.cue_player()

    assert enabled_cue_calls == []
    assert disabled_cue_calls == ["disabled"]
