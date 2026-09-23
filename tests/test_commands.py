from datetime import datetime
import re

import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.commands import CommandValidationError, HELP_MESSAGE, route_command
from deskpilot_backend.main import app


@pytest.mark.parametrize(
    ("text", "target", "display_name"),
    [
        ("open calculator", "calculator", "Calculator"),
        ("Open calculator.", "calculator", "Calculator"),
        ("  OPEN   CALCULATOR!  ", "calculator", "Calculator"),
        ("open notepad", "notepad", "Notepad"),
        ("open file explorer", "file_explorer", "File Explorer"),
        ("open explorer", "file_explorer", "File Explorer"),
        ("open settings", "settings", "Windows Settings"),
        ("open browser", "browser", "the default browser"),
    ],
)
def test_application_commands_are_recognized(
    text: str,
    target: str,
    display_name: str,
) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "open_app",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "open_app", "target": target},
        "message": (
            f"{display_name} was recognized, "
            "but DeskPilot will not launch apps yet."
        ),
    }


def test_commands_endpoint_returns_calculator_plan() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/commands", json={"text": "open calculator"})

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "planned",
        "requires_confirmation": False,
        "message": "Calculator was recognized, but DeskPilot will not launch apps yet.",
        "action": {"type": "open_app", "target": "calculator"},
    }


def test_open_calculator_ignores_case_and_surrounding_whitespace() -> None:
    response = route_command("  OPEN Calculator  ")

    assert response.intent == "open_app"
    assert response.action is not None
    assert response.action.target == "calculator"


def test_open_calculator_please_remains_unsupported() -> None:
    response = route_command("open calculator please")

    assert response.intent == "unknown"
    assert response.status == "not_supported"


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("open google", "google"),
        ("open youtube", "youtube"),
        ("open github", "github"),
    ],
)
def test_fixed_site_commands_are_recognized(text: str, target: str) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "open_site",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "open_url", "target": target},
        "message": "Website was recognized, but DeskPilot will not open it yet.",
    }


@pytest.mark.parametrize(
    ("text", "target", "query"),
    [
        ("search web for deskpilot", "web", "deskpilot"),
        ("search google for python url encoding", "google", "python url encoding"),
        ("search youtube for lo fi music", "youtube", "lo fi music"),
        ("search github for fastapi examples", "github", "fastapi examples"),
    ],
)
def test_search_commands_are_recognized(
    text: str,
    target: str,
    query: str,
) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "web_search",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "web_search", "target": target, "query": query},
        "message": "Search was recognized, but DeskPilot will not open it yet.",
    }


def test_search_query_is_not_interpreted_as_url() -> None:
    response = route_command("search google for https://example.com/delete")

    assert response.intent == "web_search"
    assert response.action is not None
    assert response.action.query == "https://example.com/delete"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("search google for", "Search query must not be empty."),
        ("search google for     ", "Search query must not be empty."),
        (
            "search youtube for line\nbreak",
            "Search query contains unsupported control characters.",
        ),
        (f"search github for {'a' * 121}", "Search query is too long."),
    ],
)
def test_invalid_search_queries_are_rejected(text: str, message: str) -> None:
    with pytest.raises(CommandValidationError, match=re.escape(message)):
        route_command(text)


def test_commands_endpoint_rejects_invalid_search_query() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/commands",
        json={"text": "search google for"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Search query must not be empty."}


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("volume up", "volume_up"),
        ("turn volume up", "volume_up"),
        ("volume down", "volume_down"),
        ("turn volume down", "volume_down"),
        ("mute", "mute"),
        ("mute volume", "mute"),
        ("play music", "play_pause"),
        ("pause music", "play_pause"),
        ("next song", "next_track"),
        ("next track", "next_track"),
        ("previous song", "previous_track"),
        ("previous track", "previous_track"),
    ],
)
def test_media_commands_are_recognized(text: str, target: str) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "media_control",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "media_key", "target": target},
        "message": "Media control was recognized, but DeskPilot will not send it yet.",
    }


def test_media_commands_keep_deterministic_normalization() -> None:
    response = route_command("  TURN   VOLUME   UP!  ")

    assert response.intent == "media_control"
    assert response.action is not None
    assert response.action.model_dump(exclude_none=True) == {
        "type": "media_key",
        "target": "volume_up",
    }


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("open downloads", "downloads"),
        ("open documents", "documents"),
        ("open desktop", "desktop"),
        ("open task manager", "task_manager"),
    ],
)
def test_workspace_shortcut_commands_are_recognized(text: str, target: str) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "workspace_shortcut",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "workspace_shortcut", "target": target},
        "message": (
            "Workspace shortcut was recognized, "
            "but DeskPilot will not open it yet."
        ),
    }


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("battery status", "battery"),
        ("what is my battery level", "battery"),
        ("memory status", "memory"),
        ("how much memory am I using", "memory"),
        ("disk space", "disk"),
        ("how much disk space do I have", "disk"),
    ],
)
def test_system_status_commands_are_recognized(text: str, target: str) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "system_status",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "system_status", "target": target},
        "message": (
            "System status request was recognized, "
            "but DeskPilot will not read it yet."
        ),
    }


@pytest.mark.parametrize("text", ["help", "what can you do"])
def test_help_commands_are_recognized(text: str) -> None:
    response = route_command(text)

    assert response.model_dump(exclude_none=True) == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": HELP_MESSAGE,
    }


@pytest.mark.parametrize("text", ["what time is it", "what's the time"])
def test_time_commands_return_local_time(text: str) -> None:
    response = route_command(
        text,
        now_factory=lambda: datetime(2026, 9, 23, 18, 30),
    )

    assert response.model_dump(exclude_none=True) == {
        "intent": "get_time",
        "status": "completed",
        "requires_confirmation": False,
        "message": "It is 6:30 PM.",
    }


@pytest.mark.parametrize("text", ["what is the date", "what's today's date"])
def test_date_commands_return_local_date(text: str) -> None:
    response = route_command(
        text,
        now_factory=lambda: datetime(2026, 9, 23, 18, 30),
    )

    assert response.model_dump(exclude_none=True) == {
        "intent": "get_date",
        "status": "completed",
        "requires_confirmation": False,
        "message": "Today is September 23, 2026.",
    }


def test_curly_apostrophes_are_normalized_for_defined_aliases() -> None:
    response = route_command(
        "What’s today’s date?",
        now_factory=lambda: datetime(2026, 9, 23, 18, 30),
    )

    assert response.intent == "get_date"
    assert response.message == "Today is September 23, 2026."


def test_unknown_command_is_not_supported() -> None:
    response = route_command("open paint")

    assert response.model_dump(exclude_none=True) == {
        "intent": "unknown",
        "status": "not_supported",
        "requires_confirmation": False,
        "message": "That command is not supported yet.",
    }


def test_unknown_media_like_command_is_not_supported() -> None:
    response = route_command("play song")

    assert response.intent == "unknown"
    assert response.status == "not_supported"


def test_unknown_workspace_like_command_is_not_supported() -> None:
    response = route_command("open pictures")

    assert response.intent == "unknown"
    assert response.status == "not_supported"


def test_unknown_status_like_command_is_not_supported() -> None:
    response = route_command("cpu status")

    assert response.intent == "unknown"
    assert response.status == "not_supported"


def test_commands_endpoint_rejects_blank_text() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/commands", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, text must not be empty"
