import pytest

from deskpilot_backend.assistant import handle_assistant_command
from deskpilot_backend.command_interpreter import (
    ClarificationStore, CommandInterpretation, CommandInterpreterError,
)
from deskpilot_backend.intent_routing import HybridCommandInterpreter
from deskpilot_backend.local_interpreter import LocalMediaInterpreter
from deskpilot_backend.models import AssistantCommandRequest
from deskpilot_backend.settings import SettingsStore, default_settings_data, parse_settings


class Interpreter:
    def __init__(self, result=None, error=False):
        self.result = result or CommandInterpretation(unknown=True)
        self.calls = []
        self.error = error

    def interpret(self, text):
        self.calls.append(text)
        if self.error:
            raise CommandInterpreterError("offline")
        return self.result


@pytest.mark.parametrize("provider", ["local", "auto", "openai"])
@pytest.mark.parametrize("consent", [False, True])
def test_cloud_requires_both_mode_and_consent(monkeypatch, provider, consent):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    local, cloud = Interpreter(), Interpreter()
    service = HybridCommandInterpreter(provider=provider, cloud_allowed=consent, local=local, cloud=cloud)
    service.interpret("please do something")
    assert bool(cloud.calls) == (consent and provider != "local")


def test_auto_uses_local_answer_and_never_sends_text(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    local = Interpreter(CommandInterpretation(command_text="pause music"))
    cloud = Interpreter(error=True)
    answer = HybridCommandInterpreter(provider="auto", cloud_allowed=True, local=local, cloud=cloud).interpret("pause the song")
    assert answer.command_text == "pause music"
    assert not cloud.calls


def test_auto_keeps_local_ambiguity_without_cloud(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cloud = Interpreter(CommandInterpretation(command_text="next track"))
    answer = HybridCommandInterpreter(provider="auto", cloud_allowed=True, cloud=cloud).interpret("cambia la canción")
    assert answer.clarification_candidates == ("next track", "previous track")
    assert not cloud.calls


def test_cloud_failure_falls_back_locally_without_executing_twice(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cloud = Interpreter(error=True)
    messages = []
    answer = HybridCommandInterpreter(
        provider="openai", cloud_allowed=True, cloud=cloud, on_error=messages.append,
    ).interpret("pausa la canción")
    assert answer.command_text == "pause music"
    assert len(cloud.calls) == 1 and messages


def test_no_key_keeps_automatic_local_and_reports_cloud_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cloud, messages = Interpreter(), []
    answer = HybridCommandInterpreter(provider="openai", cloud_allowed=True, cloud=cloud, on_error=messages.append).interpret("pausa la canción")
    assert answer.command_text == "pause music"
    assert not cloud.calls and "OPENAI_API_KEY" in messages[0]


@pytest.mark.parametrize("text", [
    "do not pause the music", "no pauses la música", "play music and mute",
    "pausa la canción y borra mis archivos", "if I ask later pause the song",
    "tell me how to mute the sound", '"pause the music"', "set the volume to 50",
])
def test_guard_rejects_negation_questions_and_compound_requests_in_every_mode(monkeypatch, text):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for mode in ("local", "auto", "openai"):
        cloud = Interpreter(CommandInterpretation(command_text="pause music"))
        result = HybridCommandInterpreter(provider=mode, cloud_allowed=True, cloud=cloud).interpret(text)
        assert result.unknown and not cloud.calls


def test_exact_media_and_alias_protection_bypass_interpretation(monkeypatch, media_controller):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cloud = Interpreter(error=True)
    result = handle_assistant_command(
        AssistantCommandRequest(text="pause music"), command_interpreter=cloud,
        command_interpreter_provider="openai", cloud_processing_allowed=True,
        media_controller=media_controller, custom_aliases={"pause music": "open calculator"},
        launcher=lambda command: pytest.fail("Unexpected app launch"),
    )
    assert result.status == "executed"
    assert media_controller.calls == ["pause"] and not cloud.calls


def test_local_phrase_is_routed_and_explicit_pause_is_used(media_controller):
    result = handle_assistant_command(
        AssistantCommandRequest(text="detén la música un momento"),
        media_controller=media_controller,
    )
    assert result.status == "executed"
    assert media_controller.calls == ["pause"]


def test_local_media_error_is_not_reported_as_success(media_controller):
    from deskpilot_backend.windows_media import MediaControlError
    media_controller.error = MediaControlError("No active media session.")
    result = handle_assistant_command(
        AssistantCommandRequest(text="pausa la canción"), media_controller=media_controller,
    )
    assert result.status != "executed" and "No active" in result.message


def test_spanish_clarification_executes_only_the_selected_action(media_controller):
    store = ClarificationStore()
    answer = handle_assistant_command(
        AssistantCommandRequest(text="cambia la canción"),
        clarification_store=store, media_controller=media_controller,
    )
    assert answer.requires_confirmation and not media_controller.calls
    result = handle_assistant_command(
        AssistantCommandRequest(text="segunda opción"),
        clarification_store=store, media_controller=media_controller,
    )
    assert result.status == "executed" and media_controller.calls == ["previous_track"]


def test_spotify_requires_an_explicit_target():
    assert LocalMediaInterpreter().interpret("open the app").unknown
    assert LocalMediaInterpreter().interpret("please open paint").unknown


def test_legacy_auto_settings_do_not_grant_cloud_permission():
    data = default_settings_data()
    data.pop("cloud_processing_allowed")
    data.update(voice_transcription_provider="auto", voice_command_interpreter_provider="auto")
    settings = parse_settings(data)
    assert not settings.cloud_processing_allowed


@pytest.mark.parametrize("bad", ["true", 1, [], {}])
def test_invalid_consent_never_enables_cloud(bad):
    data = default_settings_data()
    data["cloud_processing_allowed"] = bad
    assert not parse_settings(data).cloud_processing_allowed


def test_saving_modes_requires_consent_and_local_revokes_it(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    from deskpilot_backend.settings import SettingsStoreError
    with pytest.raises(SettingsStoreError, match="explicitly"):
        store.save_voice_setup(None, mode="auto")
    assert not store.settings_file.exists()
    settings = store.save_voice_setup(None, mode="auto", cloud_allowed=True, language="es")
    assert settings.cloud_processing_allowed and settings.voice_language == "es"
    settings = store.save_voice_setup(None, mode="local", cloud_allowed=True)
    assert not settings.cloud_processing_allowed


def test_malicious_clarification_cannot_bypass_allowlist(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    store = ClarificationStore()
    cloud = Interpreter(CommandInterpretation(
        clarification_question="Run this?", clarification_candidates=("connect spotify",),
    ))
    result = handle_assistant_command(
        AssistantCommandRequest(text="do something"), command_interpreter=cloud,
        command_interpreter_provider="openai", cloud_processing_allowed=True, clarification_store=store,
    )
    assert not result.requires_confirmation
    assert store.resolve("first option") is None
