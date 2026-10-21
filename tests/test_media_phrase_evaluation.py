"""Reviewed development and adversarial phrases; never execute actions here."""

import json
from pathlib import Path

import pytest

from deskpilot_backend.local_interpreter import LocalMediaInterpreter
from deskpilot_backend.media_phrases import MEDIA_PHRASES

CASES = json.loads((Path(__file__).parent / "fixtures/media_intents.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("text", CASES["negative"])
def test_unsupported_and_negated_phrases_never_execute(text):
    assert LocalMediaInterpreter().interpret(text).command_text is None


@pytest.mark.parametrize("text,expected", [
    (text, label) for label, texts in CASES["positive"].items() for text in texts
])
def test_supported_variants_never_choose_a_wrong_action(text, expected):
    result = LocalMediaInterpreter().interpret(text)
    assert result.command_text in {None, expected}
    if result.clarification_candidates:
        assert expected in result.clarification_candidates


def test_positive_direct_execution_coverage():
    cases = [(text, label) for label, texts in CASES["positive"].items() for text in texts]
    correct = sum(LocalMediaInterpreter().interpret(text).command_text == label for text, label in cases)
    # Coverage can be improved without trading away zero wrong executed actions
    # on the reviewed evaluation set. Unknown is safer than guessing.
    assert correct / len(cases) >= 0.70


@pytest.mark.parametrize("text,expected", CASES["ambiguous"].items())
def test_ambiguous_requests_offer_choices_without_execution(text, expected):
    result = LocalMediaInterpreter().interpret(text)
    assert result.command_text is None
    assert result.clarification_candidates == tuple(expected)


def test_evaluation_phrases_are_not_training_examples():
    training = {text for texts in MEDIA_PHRASES.values() for text in texts}
    evaluation = {text for texts in CASES["positive"].values() for text in texts}
    assert training.isdisjoint(evaluation)
