"""Fixed wake-word assets in a writable per-user cache, never the install directory."""

import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

WAKE_ASSETS = {
    "hey_jarvis_v0.1.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/hey_jarvis_v0.1.onnx",
    "melspectrogram.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx",
    "embedding_model.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx",
}


def wake_cache_directory() -> Path:
    base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / ".cache"
    return base / "DeskPilot" / "models" / "openwakeword"


def ensure_wake_models(*, directory: Path | None = None, opener=None) -> Path:
    directory = directory if directory is not None else wake_cache_directory()
    directory.mkdir(parents=True, exist_ok=True)
    open_url = opener or urlopen
    for name, url in WAKE_ASSETS.items():
        destination = directory / name
        if destination.is_file() and destination.stat().st_size > 0:
            continue
        temporary: Path | None = None
        try:
            with open_url(url, timeout=30) as response:
                expected = response.headers.get("Content-Length")
                received = 0
                with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
                    temporary = Path(output.name)
                    while chunk := response.read(65536):
                        output.write(chunk)
                        received += len(chunk)
            if received == 0 or (expected is not None and received != int(expected)):
                raise OSError("Incomplete wake-word model download. Retry preparation.")
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return directory
