"""Consent-aware local/cloud interpretation; all results still need the router."""

import os
from deskpilot_backend.command_interpreter import (
    CommandInterpretation, CommandInterpreterError, OpenAICommandInterpreter,
)
from deskpilot_backend.local_interpreter import LocalMediaInterpreter, blocked_request


class HybridCommandInterpreter:
    def __init__(self, *, provider="local", cloud_allowed=False, local=None, cloud=None, on_error=None):
        self.provider = provider
        self.cloud_allowed = cloud_allowed is True
        self.local = local or LocalMediaInterpreter()
        self.cloud = cloud
        self.on_error = on_error

    def interpret(self, text):
        # Negations/compound requests must not become an affirmative action,
        # including when a cloud model would otherwise reinterpret the wording.
        if blocked_request(text):
            return CommandInterpretation(unknown=True)
        local_result = None

        def locally():
            nonlocal local_result
            if local_result is None:
                try:
                    local_result = self.local.interpret(text)
                except Exception:
                    self._notify("Local phrase understanding is unavailable. Use an exact command.")
                    local_result = CommandInterpretation(unknown=True)
            return local_result

        if self.provider != "openai":
            result = locally()
            if not result.unknown or self.provider != "auto":
                return result
        if not self.cloud_allowed:
            if self.provider == "openai":
                self._notify("Cloud processing is not allowed. Enable it in Voice setup to use cloud mode.")
            return locally()
        if not os.getenv("OPENAI_API_KEY", "").strip():
            self._notify("Natural-language command understanding needs OPENAI_API_KEY.")
            return locally()
        try:
            result = (self.cloud or OpenAICommandInterpreter()).interpret(text)
            if not result.unknown:
                return result
        except CommandInterpreterError:
            self._notify("Natural-language command understanding is unavailable.")
        return locally()

    def _notify(self, message):
        if callable(self.on_error):
            self.on_error(message)
