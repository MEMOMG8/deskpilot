from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.commands import HELP_MESSAGE, route_command
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


def test_commands_endpoint_rejects_blank_text() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/commands", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, text must not be empty"
