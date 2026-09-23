import ctypes
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from shutil import disk_usage

from deskpilot_backend.models import ActionExecutionRequest, ActionExecutionResponse

OPEN_APP_ACTION_TYPE = "open_app"
MEDIA_KEY_ACTION_TYPE = "media_key"
WORKSPACE_SHORTCUT_ACTION_TYPE = "workspace_shortcut"
SYSTEM_STATUS_ACTION_TYPE = "system_status"
KEYEVENTF_KEYUP = 0x0002
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

ProcessLauncher = Callable[[Sequence[str]], object]
KeyEventSender = Callable[[int, int], object]
SystemStatusReader = Callable[[str], str]


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    message: str
    command: tuple[str, ...] | None = None
    virtual_key: int | None = None
    workspace_directory: str | None = None
    status_target: str | None = None
    unsupported_platform_message: str | None = None


ACTION_REGISTRY = {
    (OPEN_APP_ACTION_TYPE, "calculator"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("calc.exe",),
        message="Opening Calculator.",
    ),
    (OPEN_APP_ACTION_TYPE, "notepad"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("notepad.exe",),
        message="Opening Notepad.",
    ),
    (OPEN_APP_ACTION_TYPE, "file_explorer"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("explorer.exe",),
        message="Opening File Explorer.",
    ),
    (OPEN_APP_ACTION_TYPE, "settings"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("explorer.exe", "ms-settings:"),
        message="Opening Windows Settings.",
    ),
    (OPEN_APP_ACTION_TYPE, "browser"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=("rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"),
        message="Opening your default browser.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "volume_up"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_VOLUME_UP,
        message="Turning volume up.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "volume_down"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_VOLUME_DOWN,
        message="Turning volume down.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "mute"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_VOLUME_MUTE,
        message="Toggling mute.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "play_pause"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_MEDIA_PLAY_PAUSE,
        message="Toggling media playback.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "next_track"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_MEDIA_NEXT_TRACK,
        message="Skipping to the next track.",
    ),
    (MEDIA_KEY_ACTION_TYPE, "previous_track"): ActionDefinition(
        action_type=MEDIA_KEY_ACTION_TYPE,
        virtual_key=VK_MEDIA_PREV_TRACK,
        message="Going to the previous track.",
    ),
    (WORKSPACE_SHORTCUT_ACTION_TYPE, "downloads"): ActionDefinition(
        action_type=WORKSPACE_SHORTCUT_ACTION_TYPE,
        workspace_directory="Downloads",
        message="Opening Downloads.",
        unsupported_platform_message="Workspace shortcuts are only supported on Windows.",
    ),
    (WORKSPACE_SHORTCUT_ACTION_TYPE, "documents"): ActionDefinition(
        action_type=WORKSPACE_SHORTCUT_ACTION_TYPE,
        workspace_directory="Documents",
        message="Opening Documents.",
        unsupported_platform_message="Workspace shortcuts are only supported on Windows.",
    ),
    (WORKSPACE_SHORTCUT_ACTION_TYPE, "desktop"): ActionDefinition(
        action_type=WORKSPACE_SHORTCUT_ACTION_TYPE,
        workspace_directory="Desktop",
        message="Opening Desktop.",
        unsupported_platform_message="Workspace shortcuts are only supported on Windows.",
    ),
    (WORKSPACE_SHORTCUT_ACTION_TYPE, "task_manager"): ActionDefinition(
        action_type=WORKSPACE_SHORTCUT_ACTION_TYPE,
        command=("taskmgr.exe",),
        message="Opening Task Manager.",
        unsupported_platform_message="Workspace shortcuts are only supported on Windows.",
    ),
    (SYSTEM_STATUS_ACTION_TYPE, "battery"): ActionDefinition(
        action_type=SYSTEM_STATUS_ACTION_TYPE,
        status_target="battery",
        message="Checking battery status.",
        unsupported_platform_message="System status commands are only supported on Windows.",
    ),
    (SYSTEM_STATUS_ACTION_TYPE, "memory"): ActionDefinition(
        action_type=SYSTEM_STATUS_ACTION_TYPE,
        status_target="memory",
        message="Checking memory status.",
        unsupported_platform_message="System status commands are only supported on Windows.",
    ),
    (SYSTEM_STATUS_ACTION_TYPE, "disk"): ActionDefinition(
        action_type=SYSTEM_STATUS_ACTION_TYPE,
        status_target="disk",
        message="Checking disk space.",
        unsupported_platform_message="System status commands are only supported on Windows.",
    ),
}
SUPPORTED_ACTION_TYPES = {action_type for action_type, _target in ACTION_REGISTRY}


class UnsupportedActionError(ValueError):
    """Raised when an action is not on DeskPilot's execution allowlist."""


def execute_action(
    action: ActionExecutionRequest,
    launcher: ProcessLauncher | None = None,
    key_event_sender: KeyEventSender | None = None,
    system_status_reader: SystemStatusReader | None = None,
) -> ActionExecutionResponse:
    if action.type not in SUPPORTED_ACTION_TYPES:
        raise UnsupportedActionError(f"Unsupported action type: {action.type}")

    action_definition = ACTION_REGISTRY.get((action.type, action.target))
    if action_definition is None:
        raise UnsupportedActionError(f"Unsupported action target: {action.target}")

    message = action_definition.message

    if action_definition.unsupported_platform_message and sys.platform != "win32":
        raise UnsupportedActionError(action_definition.unsupported_platform_message)

    if action_definition.workspace_directory is not None:
        process_launcher = launcher or subprocess.Popen
        workspace_path = resolve_workspace_directory(
            action_definition.workspace_directory
        )
        process_launcher(["explorer.exe", str(workspace_path)])
    elif action_definition.command is not None:
        process_launcher = launcher or subprocess.Popen
        process_launcher(list(action_definition.command))
    elif action_definition.virtual_key is not None:
        sender = key_event_sender or send_windows_key_event
        sender(action_definition.virtual_key, 0)
        sender(action_definition.virtual_key, KEYEVENTF_KEYUP)
    elif action_definition.status_target is not None:
        reader = system_status_reader or read_windows_system_status
        message = reader(action_definition.status_target)

    return ActionExecutionResponse(
        status="executed",
        executed=True,
        action=action,
        message=message,
    )


def send_windows_key_event(virtual_key: int, flags: int) -> object:
    if sys.platform != "win32":
        raise UnsupportedActionError("Windows media controls are only supported on Windows.")

    try:
        return ctypes.windll.user32.keybd_event(virtual_key, 0, flags, 0)
    except AttributeError as error:
        raise UnsupportedActionError("Windows media controls are unavailable.") from error


def resolve_workspace_directory(directory_name: str) -> Path:
    allowed_directories = {
        "Downloads": Path.home() / "Downloads",
        "Documents": Path.home() / "Documents",
        "Desktop": Path.home() / "Desktop",
    }
    return allowed_directories[directory_name]


def read_windows_system_status(target: str) -> str:
    if sys.platform != "win32":
        raise UnsupportedActionError("System status commands are only supported on Windows.")

    if target == "battery":
        return read_windows_battery_status()
    if target == "memory":
        return read_windows_memory_status()
    if target == "disk":
        return read_windows_disk_status()

    raise UnsupportedActionError(f"Unsupported status target: {target}")


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def read_windows_battery_status() -> str:
    power_status = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power_status)):
        raise UnsupportedActionError("Battery status is unavailable.")

    if power_status.BatteryFlag == 128 or power_status.BatteryLifePercent == 255:
        return format_battery_status(None)

    return format_battery_status(power_status.BatteryLifePercent)


def read_windows_memory_status() -> str:
    memory_status = MEMORYSTATUSEX()
    memory_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
        raise UnsupportedActionError("Memory status is unavailable.")

    return format_memory_status(memory_status.dwMemoryLoad)


def read_windows_disk_status() -> str:
    system_drive = os.environ.get("SystemDrive", "C:")
    usage = disk_usage(f"{system_drive}\\")
    available_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    return format_disk_status(available_gb, total_gb, system_drive)


def format_battery_status(percent: int | None) -> str:
    if percent is None:
        return "No battery detected."

    return f"Battery is at {percent}%."


def format_memory_status(memory_load_percent: int) -> str:
    return f"Memory usage is {memory_load_percent}%."


def format_disk_status(available_gb: float, total_gb: float, drive: str) -> str:
    return (
        f"Disk space is {available_gb:.1f} GB available "
        f"of {total_gb:.1f} GB on {drive}."
    )
