from fastapi.testclient import TestClient

from deskpilot_backend.commands import route_command
from deskpilot_backend.main import app


def test_open_calculator_is_recognized() -> None:
    response = route_command("open calculator")

    assert response.model_dump(exclude_none=True) == {
        "intent": "open_app",
        "status": "planned",
        "requires_confirmation": False,
        "action": {"type": "open_app", "target": "calculator"},
        "message": "Calculator was recognized, but DeskPilot will not launch apps yet.",
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


def test_help_is_recognized() -> None:
    response = route_command("help")

    assert response.model_dump(exclude_none=True) == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": 'Supported commands: "open calculator" and "help".',
    }


def test_unknown_command_is_not_supported() -> None:
    response = route_command("open notepad")

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
