"""Small, offline, example-based EN/ES media classifier with abstention.

TF-IDF word/character features learn vocabulary weights from reviewed examples.
Cosine similarity is not a calibrated probability. No language model, downloads,
network calls, arbitrary execution or runtime learning occurs here.
"""

import re
import threading
import unicodedata
from functools import lru_cache

from deskpilot_backend.command_interpreter import CommandInterpretation
from deskpilot_backend.media_phrases import MEDIA_PHRASES, NEGATIVE_PHRASES

_MODEL_LOCK = threading.Lock()
_BLOCKED_WORDS = re.compile(
    r"\b(no|not|dont|don't|never|nunca|jamas|sin|without|except|unless|if|si|"
    r"and|then|after|before|y|luego|despues|antes|or|o|"
    r"delete|remove|erase|borra|borres|elimina|download|descarga|install|instala|"
    r"oauth|token|password|contrasena|powershell|cmd|execute|ejecuta|script|"
    r"unmute|desilencia|restart|reinicia|seek|adelanta|"
    r"website|web|browser|navegador|album|playlist|jazz|rock|"
    r"how|why|explain|tell|como|porque|explica|dime|says|said|dice|dijo|"
    r"subscription|suscripcion|premium|account|cuenta)\b"
)
_REQUEST_START = re.compile(
    r"^(open|launch|bring|start|play|resume|continue|put|pause|stop|skip|go|move|return|"
    r"increase|raise|make|turn|decrease|lower|reduce|mute|toggle|silence|next|previous|back|"
    r"abre|abrir|inicia|quiero|pon|reproduce|reanuda|continua|sigue|pausa|deten|para|"
    r"pasa|siguiente|salta|cambia|avanza|vuelve|cancion|regresa|retrocede|sube|subir|"
    r"aumenta|mas|haz|baja|bajar|menos|silencia|activa)\b"
)
_STOP_WORDS = [
    "the", "a", "an", "this", "that", "my", "me", "it", "to", "some", "please",
    "el", "la", "los", "las", "un", "una", "esta", "este", "mi", "de", "algo",
]
_KNOWN_WORDS = frozenset(
    word for phrases in (*MEDIA_PHRASES.values(), NEGATIVE_PHRASES)
    for phrase in phrases for word in phrase.split()
) | {"little", "bit", "slightly", "now", "poco", "poquito", "momento", "favor", "por", "algo"}
_SPANISH_INFINITIVES = {
    "abrir": "abre", "iniciar": "inicia", "reanudar": "reanuda", "pausar": "pausa",
    "poner": "pon", "volver": "vuelve", "silenciar": "silencia",
    "subir": "sube", "bajar": "baja", "reproducir": "reproduce",
}


def normalize_phrase(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    text = text.replace("’", "'").strip().rstrip(".!?")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(?:(?:could you|can you|would you|please|por favor|puedes|podrias)\s+)+", "", text)
    text = re.sub(r"(?:,?\s+(?:please|por favor|for me|para mi|right now|ahora|un momento|for a moment))+$", "", text)
    text = " ".join(_SPANISH_INFINITIVES.get(word, word) for word in text.split())
    return text


def blocked_request(text):
    normalized = normalize_phrase(text)
    return (
        not normalized or len(text) > 240
        or any(ord(c) < 32 for c in text)
        or bool(re.search(r'[0-9;:/\\&|<>="{}“”]|\.\s', normalized))
        or bool(_BLOCKED_WORDS.search(normalized))
    )


def clarification(candidates):
    choices = tuple(candidates[:2])
    labels = "; ".join(f"{i + 1}: {c}" for i, c in enumerate(choices))
    return CommandInterpretation(
        clarification_question=f"Did you mean {labels}? Say first option / primera opcion"
        + (" or second option / segunda opcion." if len(choices) > 1 else "."),
        clarification_candidates=choices,
    )


@lru_cache(maxsize=1)
def _trained_classifier():
    # Fit lazily on a voice worker, once per process. Imports stay out of UI startup.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    from sklearn.preprocessing import normalize

    texts, labels = [], []
    for label, examples in {**MEDIA_PHRASES, "unknown": NEGATIVE_PHRASES}.items():
        for example in examples:
            texts.append(normalize_phrase(example))
            labels.append(label)
    features = FeatureUnion([
        ("words", TfidfVectorizer(sublinear_tf=True, stop_words=_STOP_WORDS)),
        ("characters", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
    ], transformer_weights={"words": 1.0, "characters": 0.5})
    matrix = normalize(features.fit_transform(texts))
    return features, matrix, tuple(labels)


class LocalMediaInterpreter:
    def scores(self, text):
        from sklearn.preprocessing import normalize
        with _MODEL_LOCK:
            features, matrix, labels = _trained_classifier()
        vector = normalize(features.transform([normalize_phrase(text)]))
        similarities = (matrix @ vector.T).toarray().ravel()
        scores = {}
        for label, value in zip(labels, similarities):
            scores[label] = max(scores.get(label, 0.0), float(value))
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)

    def interpret(self, transcript):
        text = normalize_phrase(transcript)
        ambiguous = {
            "change the music": ("next track", "previous track"),
            "change the song": ("next track", "previous track"),
            "cambia la musica": ("next track", "previous track"),
            "cambia la cancion": ("next track", "previous track"),
            "change the volume": ("volume up", "volume down"),
            "cambia el volumen": ("volume up", "volume down"),
        }
        if text in ambiguous:
            return clarification(ambiguous[text])
        if blocked_request(transcript):
            return CommandInterpretation(unknown=True)
        if not _REQUEST_START.search(text):
            return CommandInterpretation(unknown=True)
        # TF-IDF ignores unseen words. Never silently drop a new target such as
        # "picture" in "make the picture louder" and execute the remaining words.
        if any(word not in _KNOWN_WORDS for word in re.findall(r"\w+", text)):
            return CommandInterpretation(unknown=True)
        ranked = self.scores(text)
        (label, score), (_, runner_up) = ranked[:2]
        if label == "open spotify" and "spotify" not in text.split():
            return CommandInterpretation(unknown=True)
        if label == "unknown" or score < 0.48:
            return CommandInterpretation(unknown=True)
        if score >= 0.72 and score - runner_up >= 0.12:
            return CommandInterpretation(command_text=label)
        candidates = [label]
        if ranked[1][0] != "unknown" and runner_up >= 0.45:
            candidates.append(ranked[1][0])
        return clarification(candidates)
