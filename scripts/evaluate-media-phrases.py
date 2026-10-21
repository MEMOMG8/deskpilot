"""Offline coverage/latency measurement of reviewed phrases, never voice actions."""

import json
import statistics
import time
from pathlib import Path

from deskpilot_backend.local_interpreter import LocalMediaInterpreter, _trained_classifier

root = Path(__file__).resolve().parents[1]
cases = json.loads((root / "tests/fixtures/media_intents.json").read_text(encoding="utf-8"))
classifier = LocalMediaInterpreter()
start = time.perf_counter()
classifier.interpret("pause the music")
cold_ms = (time.perf_counter() - start) * 1000
positive = [(text, label) for label, texts in cases["positive"].items() for text in texts]
correct, wrong, clarified, elapsed, abstentions = 0, [], 0, [], []
for text, expected in positive:
    start = time.perf_counter()
    result = classifier.interpret(text)
    elapsed.append((time.perf_counter() - start) * 1000)
    correct += result.command_text == expected
    clarified += bool(result.clarification_candidates)
    if result.command_text not in {None, expected}:
        wrong.append(text)
    if result.command_text is None:
        abstentions.append(text)
false_actions = [text for text in cases["negative"] if classifier.interpret(text).command_text]
_, matrix, _ = _trained_classifier()
report = {
    "dataset": "Reviewed development phrases, not an independent real-user accuracy estimate",
    "positive_count": len(positive), "correct_direct": correct, "clarified": clarified,
    "coverage": correct / len(positive), "wrong_actions": wrong,
    "negative_count": len(cases["negative"]), "false_actions": false_actions,
    "cold_import_and_fit_ms": round(cold_ms, 2),
    "warm_median_ms": round(statistics.median(elapsed), 2), "warm_max_ms": round(max(elapsed), 2),
    "abstentions": abstentions,
    "training_matrix_bytes": matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes,
}
print(json.dumps(report, indent=2, ensure_ascii=False))
raise SystemExit(0 if not wrong and not false_actions and report["coverage"] >= 0.70 else 1)
