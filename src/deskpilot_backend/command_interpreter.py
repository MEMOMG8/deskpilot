import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol

from deskpilot_backend.commands import (
    APPLICATION_COMMANDS,
    CANCEL_COMMANDS,
    DATE_COMMANDS,
    DESKPILOT_SETTINGS_COMMANDS,
    FIXED_SITE_COMMANDS,
    HELP_COMMANDS,
    MEDIA_COMMANDS,
    NOTE_COMMANDS,
    REMINDER_COMMANDS,
    SEARCH_COMMAND_PREFIXES,
    SYSTEM_STATUS_COMMANDS,
    TIME_COMMANDS,
    WORKSPACE_COMMANDS,
    normalize_command_text,
)

OPENAI_COMMAND_INTERPRETER_MODEL = "gpt-6-luna"
COMMAND_CLARIFICATION_TTL_SECONDS = 20.0
DEFAULT_COMMAND_INTERPRETER_PROVIDER = "auto"
InterpreterProvider = Literal["auto", "local", "openai"]
ApiKeyGetter = Callable[[str], str | None]
OpenAIClientFactory = Callable[[str], object]


class CommandInterpreterError(RuntimeError):
    """Raised when cloud command interpretation cannot complete safely."""


class CommandInterpreter(Protocol):
    def interpret(self, transcript: str) -> "CommandInterpretation":
        """Interpret one natural-language transcript into a safe local outcome."""


@dataclass(frozen=True)
class CommandInterpretation:
    command_text: str | None = None
    clarification_question: str | None = None
    clarification_candidates: tuple[str, ...] = ()
    unknown: bool = False


@dataclass
class PendingClarification:
    candidates: tuple[str, ...]
    expires_at: float


class ClarificationStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        ttl_seconds: float = COMMAND_CLARIFICATION_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._pending: PendingClarification | None = None

    def set(self, candidates: Sequence[str]) -> None:
        self._pending = PendingClarification(
            candidates=tuple(candidates),
            expires_at=self._clock() + self._ttl_seconds,
        )

    def clear(self) -> None:
        self._pending = None

    def resolve(self, text: str) -> str | None:
        if self._pending is None:
            return None

        if self._clock() > self._pending.expires_at:
            self.clear()
            return None

        normalized_text = normalize_command_text(text)
        if normalized_text in {"cancel", "never mind"}:
            self.clear()
            return "cancel"

        if normalized_text == "first option" and len(self._pending.candidates) >= 1:
            command_id = self._pending.candidates[0]
            self.clear()
            return command_id

        if normalized_text == "second option" and len(self._pending.candidates) >= 2:
            command_id = self._pending.candidates[1]
            self.clear()
            return command_id

        self.clear()
        return None


class OpenAICommandInterpreter:
    def __init__(
        self,
        *,
        api_key_getter: ApiKeyGetter | None = None,
        client_factory: OpenAIClientFactory | None = None,
    ) -> None:
        self._api_key_getter = api_key_getter or os.getenv
        self._client_factory = client_factory or _default_openai_client_factory

    def interpret(self, transcript: str) -> CommandInterpretation:
        api_key = self._api_key_getter("OPENAI_API_KEY")
        if not isinstance(api_key, str) or not api_key.strip():
            raise CommandInterpreterError(
                "Natural-language command understanding requires OPENAI_API_KEY."
            )

        try:
            client = self._client_factory(api_key.strip())
            response = client.responses.create(
                model=OPENAI_COMMAND_INTERPRETER_MODEL,
                instructions=_interpreter_instructions(),
                input=_interpreter_input(transcript),
                tools=build_interpreter_tools(),
                tool_choice="required",
                parallel_tool_calls=False,
                max_tool_calls=1,
                max_output_tokens=300,
                store=False,
            )
            return parse_interpreter_response(response)
        except CommandInterpreterError:
            raise
        except Exception as error:
            raise CommandInterpreterError(
                "Natural-language command understanding is unavailable."
            ) from error


def fixed_command_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            set(APPLICATION_COMMANDS)
            | set(FIXED_SITE_COMMANDS)
            | set(MEDIA_COMMANDS)
            | set(WORKSPACE_COMMANDS)
            | set(SYSTEM_STATUS_COMMANDS)
            | set(NOTE_COMMANDS)
            | set(DESKPILOT_SETTINGS_COMMANDS)
            | set(REMINDER_COMMANDS)
            | set(TIME_COMMANDS)
            | set(DATE_COMMANDS)
            | set(CANCEL_COMMANDS)
            | set(HELP_COMMANDS)
        )
    )


def build_interpreter_tools() -> list[dict[str, object]]:
    command_ids = list(fixed_command_ids())
    search_targets = sorted(set(SEARCH_COMMAND_PREFIXES.values()))
    return [
        _function_tool(
            "choose_fixed_command",
            "Choose one exact existing fixed DeskPilot command ID.",
            {
                "type": "object",
                "properties": {"command_id": {"type": "string", "enum": command_ids}},
                "required": ["command_id"],
                "additionalProperties": False,
            },
        ),
        _function_tool(
            "create_note",
            "Create one local DeskPilot note with user-provided text.",
            {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        ),
        _function_tool(
            "create_reminder",
            "Create one local DeskPilot reminder.",
            {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
                    "text": {"type": "string"},
                },
                "required": ["minutes", "text"],
                "additionalProperties": False,
            },
        ),
        _function_tool(
            "safe_search",
            "Search a trusted site with a query that local code will validate.",
            {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": search_targets},
                    "query": {"type": "string"},
                },
                "required": ["target", "query"],
                "additionalProperties": False,
            },
        ),
        _function_tool(
            "ask_clarification",
            "Ask a concise question with one or two existing fixed command choices.",
            {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "candidates": {
                        "type": "array",
                        "items": {"type": "string", "enum": command_ids},
                        "minItems": 1,
                        "maxItems": 2,
                    },
                },
                "required": ["question", "candidates"],
                "additionalProperties": False,
            },
        ),
        _function_tool(
            "unknown_command",
            "Use when the command is unsupported or unsafe.",
            {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
    ]


def parse_interpreter_response(response: object) -> CommandInterpretation:
    tool_calls = [
        item
        for item in _response_output_items(response)
        if _value(item, "type") == "function_call"
    ]
    if len(tool_calls) != 1:
        raise CommandInterpreterError("Expected exactly one command interpretation.")

    tool_call = tool_calls[0]
    name = _value(tool_call, "name")
    arguments = _parse_arguments(_value(tool_call, "arguments"))

    if name == "choose_fixed_command":
        command_id = _required_string(arguments, "command_id")
        if command_id not in fixed_command_ids():
            raise CommandInterpreterError("Unsupported fixed command.")
        return CommandInterpretation(command_text=command_id)

    if name == "create_note":
        return CommandInterpretation(
            command_text=f"note {_required_string(arguments, 'text')}"
        )

    if name == "create_reminder":
        minutes = arguments.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            raise CommandInterpreterError("Reminder minutes are invalid.")
        text = _required_string(arguments, "text")
        return CommandInterpretation(
            command_text=f"remind me in {minutes} minutes to {text}"
        )

    if name == "safe_search":
        target = _required_string(arguments, "target")
        if target not in set(SEARCH_COMMAND_PREFIXES.values()):
            raise CommandInterpreterError("Search target is unsupported.")
        return CommandInterpretation(
            command_text=f"search {target} for {_required_string(arguments, 'query')}"
        )

    if name == "ask_clarification":
        question = _required_string(arguments, "question")
        candidates = arguments.get("candidates")
        if not isinstance(candidates, list) or len(candidates) not in {1, 2}:
            raise CommandInterpreterError("Clarification candidates are invalid.")
        normalized_candidates = tuple(
            candidate for candidate in candidates if isinstance(candidate, str)
        )
        if len(normalized_candidates) != len(candidates) or any(
            candidate not in fixed_command_ids() for candidate in normalized_candidates
        ):
            raise CommandInterpreterError("Clarification candidate is unsupported.")
        return CommandInterpretation(
            clarification_question=question,
            clarification_candidates=normalized_candidates,
        )

    if name == "unknown_command":
        return CommandInterpretation(unknown=True)

    raise CommandInterpreterError("Unsupported command interpretation.")


def _function_tool(
    name: str,
    description: str,
    parameters: dict[str, object],
) -> dict[str, object]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "strict": True,
    }


def _interpreter_instructions() -> str:
    return (
        "You interpret one English DeskPilot transcript into exactly one function "
        "call. Do not execute actions. Do not call built-in tools. Use only the "
        "provided functions. Prefer choose_fixed_command when the request clearly "
        "maps to an existing fixed command. Use create_note, create_reminder, or "
        "safe_search only for those exact supported user intents. Ask clarification "
        "only when one or two fixed command choices are plausible. Otherwise use "
        "unknown_command."
    )


def _interpreter_input(transcript: str) -> str:
    return (
        "Current transcript only. Do not assume private notes, reminders, settings, "
        f"history, paths, URLs, or files.\nTranscript: {transcript}"
    )


def _response_output_items(response: object) -> list[object]:
    output = _value(response, "output")
    return output if isinstance(output, list) else []


def _value(item: object, key: str) -> object:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _parse_arguments(raw_arguments: object) -> dict[str, object]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        parsed_arguments = json.loads(raw_arguments)
        if isinstance(parsed_arguments, dict):
            return parsed_arguments
    raise CommandInterpreterError("Command interpretation arguments are invalid.")


def _required_string(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise CommandInterpreterError(f"{key} is required.")
    return value


def _default_openai_client_factory(api_key: str) -> object:
    from openai import OpenAI

    return OpenAI(api_key=api_key)
