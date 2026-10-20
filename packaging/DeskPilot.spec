# PyInstaller recipe. Keep model caches and user data out of the distribution.
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], [
    "pyttsx3.drivers.sapi5", "pythoncom", "pywintypes", "win32com.client",
    "winrt.windows.foundation", "winrt.windows.foundation.collections",
    "winrt.windows.media.control",
]
for package in (
    "pyttsx3", "sounddevice", "openwakeword", "faster_whisper",
    "openai", "ctranslate2", "av", "onnxruntime", "winrt",
):
    data, binary, hidden = collect_all(package, include_py_files=False)
    if package == "openwakeword":
        data = [(source, target) for source, target in data
                if "resources/models" not in str(Path(target)).replace("\\", "/")]
    datas.extend(data)
    binaries.extend(binary)
    hiddenimports.extend(hidden)
for distribution in ("deskpilot", "openwakeword", "faster-whisper", "openai", "pyttsx3", "sounddevice"):
    datas.extend(copy_metadata(distribution))

datas = [(source, target) for source, target in datas
         if Path(source).suffix.lower() not in {".onnx", ".tflite", ".wav", ".mp3"}]

a = Analysis(
    [str(root / "src/deskpilot_backend/desktop_entry.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=["pytest"], noarchive=False,
)
# Metadata directories are expanded by Analysis, so filter again afterwards.
a.datas = [
    entry for entry in a.datas
    if "__pycache__" not in Path(entry[0]).parts
    and Path(entry[0]).name != "direct_url.json"
    and Path(entry[0]).suffix.lower() not in {".onnx", ".tflite", ".wav", ".mp3"}
]
trusted_library_roots = [
    Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
    Path(os.environ["SystemRoot"]).resolve(),
]
for destination, source, kind in a.binaries:
    if not any(Path(source).resolve().is_relative_to(base) for base in trusted_library_roots):
        raise RuntimeError(f"Library came from outside Python/Windows: {destination}")
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="DeskPilot",
    console=False, debug=False, strip=False, upx=False,
    version=str(root / "packaging/version-info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DeskPilot")
