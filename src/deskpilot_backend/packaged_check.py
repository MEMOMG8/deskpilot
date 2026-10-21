"""Read-only runtime checks for a test distribution; no recording or model download."""

import asyncio
import importlib
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run_checks(report_path: Path) -> int:
    checks = {}
    frozen = bool(getattr(sys, "frozen", False))
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()

    def check(name, operation):
        try:
            details = operation()
            checks[name] = {"ok": True, "details": details}
        except Exception as error:
            checks[name] = {"ok": False, "error": f"{type(error).__name__}: {error}"}

    def imports():
        names = [
            "deskpilot_backend.desktop", "deskpilot_backend.voice_setup_ui",
            "PySide6.QtCore", "PySide6.QtWidgets", "sounddevice", "_sounddevice_data",
            "pyttsx3.drivers.sapi5", "faster_whisper", "ctranslate2",
            "onnxruntime", "openwakeword.model", "av", "tokenizers",
            "winrt.windows.foundation", "winrt.windows.foundation.collections",
            "winrt.windows.media.control",
        ]
        for name in names:
            module = importlib.import_module(name)
            if frozen and getattr(module, "__file__", None):
                if not Path(module.__file__).resolve().is_relative_to(bundle):
                    raise RuntimeError(f"{name} was loaded outside the bundle")
        return names

    def ui():
        from PySide6.QtWidgets import QApplication
        from deskpilot_backend.settings import DeskPilotSettings, SettingsStore
        from deskpilot_backend.voice_setup import VoiceModelResources
        from deskpilot_backend.voice_setup_ui import VoiceSetupDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="deskpilot-ui-check-") as directory:
            dialog = VoiceSetupDialog(
                SettingsStore(Path(directory) / "settings.json"),
                DeskPilotSettings(), VoiceModelResources(),
            )
            dialog.show()
            app.processEvents()
            if not dialog.isVisible() or dialog.save_button.isEnabled():
                raise RuntimeError("Setup dialog did not initialize safely")
            dialog.close()
            app.processEvents()
        return {"platform": app.platformName(), "setup": "initialized without recording"}

    def audio():
        import sounddevice
        return {"host_apis": len(sounddevice.query_hostapis()), "devices": len(sounddevice.query_devices())}

    def tts():
        import pyttsx3
        engine = pyttsx3.init(driverName="sapi5")
        count = len(engine.getProperty("voices"))
        engine.stop()
        if not count:
            raise RuntimeError("No Windows SAPI voices found")
        return {"voices": count, "spoken": False}

    def media():
        from deskpilot_backend.windows_media import _request_windows_manager
        async def inspect():
            manager = await asyncio.wait_for(_request_windows_manager(), timeout=10)
            return {"sessions": len(manager.get_sessions()), "command_sent": False}
        with ThreadPoolExecutor(max_workers=1) as worker:
            return worker.submit(lambda: asyncio.run(inspect())).result(timeout=15)

    def inference():
        import ctranslate2
        import onnxruntime
        return {
            "cpu_compute_types": sorted(ctranslate2.get_supported_compute_types("cpu")),
            "onnx_providers": onnxruntime.get_available_providers(),
        }

    def local_phrases():
        from deskpilot_backend.local_interpreter import LocalMediaInterpreter
        interpreter = LocalMediaInterpreter()
        for phrase in ("pause the song", "pausa la canción"):
            if interpreter.interpret(phrase).command_text != "pause music":
                raise RuntimeError("Local media interpretation failed")
        if not interpreter.interpret("no pauses la música").unknown:
            raise RuntimeError("Negated phrase was accepted")
        return {"languages": ["en", "es"], "network": False, "command_sent": False}

    check("bundled_imports", imports)
    check("qt_setup", ui)
    check("audio_devices", audio)
    check("sapi_tts", tts)
    check("windows_media", media)
    check("inference_engines", inference)
    check("local_media_phrases", local_phrases)
    ok = all(result["ok"] for result in checks.values())
    report_path.write_text(
        json.dumps({"ok": ok, "frozen": frozen, "checks": checks}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if ok else 1
