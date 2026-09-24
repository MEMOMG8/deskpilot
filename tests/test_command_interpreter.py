import json
from dataclasses import dataclass

import pytest

from deskpilot_backend.command_interpreter import (
    ClarificationStore,
    CommandInterpreterError,
    OpenAICommandInterpreter,
    build_interpreter_tools,
    parse_interpreter_response,
)


@dataclass
class FakeFunctionCall:
    name: str
    arguments: str
    type: str = "function_call"


@dataclass
class FakeResponse:
    output: list[object]


class FakeResponses:
    def __init__(self, response: FakeResponse, *, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("network down")
        return self.response


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def function_response(name: str, arguments: dict[str, object]) -> FakeResponse:
    return FakeResponse([FakeFunctionCall(name, json.dumps(arguments))])


def test_openai_interpreter_uses_responses_api_safely(monkeypatch) -> None:
    responses = FakeResponses(
        function_response("choose_fixed_command", {"command_id": "open notepad"})
    )
    interpreter = OpenAICommandInterpreter(
        api_key_getter=lambda name: "test-key",
        client_factory=lambda api_key: FakeClient(responses),
    )

    result = interpreter.interpret("Could you please open Notepad for me?")

    assert result.command_text == "open notepad"
    call = responses.calls[0]
    assert call["model"] == "gpt-6-luna"
    assert call["store"] is False
    assert call["parallel_tool_calls"] is False
    assert call["max_tool_calls"] == 1
    assert call["tool_choice"] == "required"
    assert all(tool["type"] == "function" for tool in call["tools"])
    assert not any(tool["type"] != "function" for tool in call["tools"])
    assert all(tool["strict"] is True for tool in call["tools"])
    assert all(
        tool["parameters"]["additionalProperties"] is False
        for tool in call["tools"]
    )
    assert "Could you please open Notepad for me?" in call["input"]


def test_openai_interpreter_requires_api_key() -> None:
    interpreter = OpenAICommandInterpreter(api_key_getter=lambda name: None)

    with pytest.raises(CommandInterpreterError) as error:
        interpreter.interpret("open notepad please")

    assert str(error.value) == (
        "Natural-language command understanding requires OPENAI_API_KEY."
    )


def test_openai_interpreter_failure_is_controlled() -> None:
    responses = FakeResponses(
        function_response("choose_fixed_command", {"command_id": "open notepad"}),
        fail=True,
    )
    interpreter = OpenAICommandInterpreter(
        api_key_getter=lambda name: "test-key",
        client_factory=lambda api_key: FakeClient(responses),
    )

    with pytest.raises(CommandInterpreterError) as error:
        interpreter.interpret("open notepad please")

    assert str(error.value) == "Natural-language command understanding is unavailable."


def test_parse_interpreter_response_rejects_malformed_payloads() -> None:
    with pytest.raises(CommandInterpreterError):
        parse_interpreter_response(
            function_response("choose_fixed_command", {"command_id": "open paint"})
        )

    with pytest.raises(CommandInterpreterError):
        parse_interpreter_response(
            FakeResponse(
                [
                    FakeFunctionCall("unknown_command", "{}"),
                    FakeFunctionCall("unknown_command", "{}"),
                ]
            )
        )


def test_parse_parameterized_interpreter_results() -> None:
    assert (
        parse_interpreter_response(
            function_response("create_note", {"text": "Buy milk"})
        ).command_text
        == "note Buy milk"
    )
    assert (
        parse_interpreter_response(
            function_response(
                "create_reminder",
                {"minutes": 5, "text": "Stretch"},
            )
        ).command_text
        == "remind me in 5 minutes to Stretch"
    )
    assert (
        parse_interpreter_response(
            function_response(
                "safe_search",
                {"target": "github", "query": "fastapi examples"},
            )
        ).command_text
        == "search github for fastapi examples"
    )


def test_parse_clarification_and_unknown_results() -> None:
    clarification = parse_interpreter_response(
        function_response(
            "ask_clarification",
            {
                "question": "Did you mean open Notepad or open Calculator?",
                "candidates": ["open notepad", "open calculator"],
            },
        )
    )
    assert clarification.clarification_question == (
        "Did you mean open Notepad or open Calculator?"
    )
    assert clarification.clarification_candidates == (
        "open notepad",
        "open calculator",
    )

    unknown = parse_interpreter_response(function_response("unknown_command", {}))

    assert unknown.unknown is True


def test_clarification_store_lifecycle_and_expiration() -> None:
    now = 100.0
    store = ClarificationStore(clock=lambda: now, ttl_seconds=20)

    store.set(["open notepad", "open calculator"])
    assert store.resolve("first option") == "open notepad"

    store.set(["open notepad", "open calculator"])
    assert store.resolve("second option") == "open calculator"

    store.set(["open notepad"])
    assert store.resolve("cancel") == "cancel"

    store.set(["open notepad"])
    assert store.resolve("open calculator") is None

    now = 200.0
    store.set(["open notepad"])
    now = 221.0
    assert store.resolve("first option") is None


def test_interpreter_tools_derive_fixed_command_ids_and_exclude_builtins() -> None:
    tools = build_interpreter_tools()
    fixed_tool = next(tool for tool in tools if tool["name"] == "choose_fixed_command")
    command_ids = fixed_tool["parameters"]["properties"]["command_id"]["enum"]

    assert "open notepad" in command_ids
    assert "open calculator" in command_ids
    assert "search google for" not in command_ids
    assert all(tool["type"] == "function" for tool in tools)
