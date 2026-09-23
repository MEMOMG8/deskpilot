import ctypes
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from shutil import disk_usage
from urllib.parse import urlencode

from deskpilot_backend.models import ActionExecutionRequest, ActionExecutionResponse
from deskpilot_backend.notes import (
    MAX_NOTE_TEXT_LENGTH,
    NoteStore,
    NoteStoreError,
    format_latest_note,
    format_note_count,
)
from deskpilot_backend.reminders import (
    MAX_REMINDER_TEXT_LENGTH,
    ReminderService,
    ReminderStoreError,
)
from deskpilot_backend.settings import SettingsStore, SettingsStoreError

OPEN_APP_ACTION_TYPE = "open_app"
MEDIA_KEY_ACTION_TYPE = "media_key"
WORKSPACE_SHORTCUT_ACTION_TYPE = "workspace_shortcut"
SYSTEM_STATUS_ACTION_TYPE = "system_status"
OPEN_URL_ACTION_TYPE = "open_url"
WEB_SEARCH_ACTION_TYPE = "web_search"
NOTE_ACTION_TYPE = "note"
REMINDER_ACTION_TYPE = "reminder"
DESKPILOT_SETTINGS_ACTION_TYPE = "deskpilot_settings"
MAX_SEARCH_QUERY_LENGTH = 120
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
    url: str | None = None
    search_url: str | None = None
    query_message_prefix: str | None = None
    note_operation: str | None = None
    reminder_operation: str | None = None
    settings_operation: str | None = None
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
    (OPEN_URL_ACTION_TYPE, "google"): ActionDefinition(
        action_type=OPEN_URL_ACTION_TYPE,
        url="https://www.google.com/",
        message="Opening Google.",
    ),
    (OPEN_URL_ACTION_TYPE, "youtube"): ActionDefinition(
        action_type=OPEN_URL_ACTION_TYPE,
        url="https://www.youtube.com/",
        message="Opening YouTube.",
    ),
    (OPEN_URL_ACTION_TYPE, "github"): ActionDefinition(
        action_type=OPEN_URL_ACTION_TYPE,
        url="https://github.com/",
        message="Opening GitHub.",
    ),
    (WEB_SEARCH_ACTION_TYPE, "web"): ActionDefinition(
        action_type=WEB_SEARCH_ACTION_TYPE,
        search_url="https://www.google.com/search",
        query_message_prefix="Searching the web for",
        message="Searching the web.",
    ),
    (WEB_SEARCH_ACTION_TYPE, "google"): ActionDefinition(
        action_type=WEB_SEARCH_ACTION_TYPE,
        search_url="https://www.google.com/search",
        query_message_prefix="Searching Google for",
        message="Searching Google.",
    ),
    (WEB_SEARCH_ACTION_TYPE, "youtube"): ActionDefinition(
        action_type=WEB_SEARCH_ACTION_TYPE,
        search_url="https://www.youtube.com/results",
        query_message_prefix="Searching YouTube for",
        message="Searching YouTube.",
    ),
    (WEB_SEARCH_ACTION_TYPE, "github"): ActionDefinition(
        action_type=WEB_SEARCH_ACTION_TYPE,
        search_url="https://github.com/search",
        query_message_prefix="Searching GitHub for",
        message="Searching GitHub.",
    ),
    (NOTE_ACTION_TYPE, "create"): ActionDefinition(
        action_type=NOTE_ACTION_TYPE,
        note_operation="create",
        message="Note saved.",
    ),
    (NOTE_ACTION_TYPE, "read_latest"): ActionDefinition(
        action_type=NOTE_ACTION_TYPE,
        note_operation="read_latest",
        message="Reading latest note.",
    ),
    (NOTE_ACTION_TYPE, "count"): ActionDefinition(
        action_type=NOTE_ACTION_TYPE,
        note_operation="count",
        message="Counting notes.",
    ),
    (NOTE_ACTION_TYPE, "open_folder"): ActionDefinition(
        action_type=NOTE_ACTION_TYPE,
        note_operation="open_folder",
        message="Opening notes folder.",
        unsupported_platform_message="Notes folder opening is only supported on Windows.",
    ),
    (REMINDER_ACTION_TYPE, "create"): ActionDefinition(
        action_type=REMINDER_ACTION_TYPE,
        reminder_operation="create",
        message="Reminder set.",
    ),
    (REMINDER_ACTION_TYPE, "list"): ActionDefinition(
        action_type=REMINDER_ACTION_TYPE,
        reminder_operation="list",
        message="Listing reminders.",
    ),
    (DESKPILOT_SETTINGS_ACTION_TYPE, "open_file"): ActionDefinition(
        action_type=DESKPILOT_SETTINGS_ACTION_TYPE,
        settings_operation="open_file",
        message="Opening DeskPilot settings.",
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
    note_store: NoteStore | None = None,
    reminder_service: ReminderService | None = None,
    settings_store: SettingsStore | None = None,
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
    elif action_definition.url is not None:
        open_trusted_url(action_definition.url, launcher=launcher)
    elif action_definition.search_url is not None:
        query = validate_search_query(action.query)
        search_url = build_search_url(action_definition.search_url, query)
        open_trusted_url(search_url, launcher=launcher)
        message = f"{action_definition.query_message_prefix} {query}."
    elif action_definition.note_operation is not None:
        message = execute_note_operation(
            action_definition.note_operation,
            action,
            note_store=note_store,
            launcher=launcher,
        )
    elif action_definition.reminder_operation is not None:
        message = execute_reminder_operation(
            action_definition.reminder_operation,
            action,
            reminder_service=reminder_service,
        )
    elif action_definition.settings_operation is not None:
        message = execute_settings_operation(
            action_definition.settings_operation,
            settings_store=settings_store,
            launcher=launcher,
        )

    return ActionExecutionResponse(
        status="executed",
        executed=True,
        action=action,
        message=message,
    )


def execute_settings_operation(
    operation: str,
    *,
    settings_store: SettingsStore | None = None,
    launcher: ProcessLauncher | None = None,
) -> str:
    store = settings_store or SettingsStore()

    try:
        if operation == "open_file":
            settings_file = store.ensure_settings_file()
            process_launcher = launcher or subprocess.Popen
            process_launcher(["notepad.exe", str(settings_file)])
            return "Opening DeskPilot settings."
    except SettingsStoreError as error:
        raise UnsupportedActionError(str(error)) from error
    except OSError as error:
        raise UnsupportedActionError("DeskPilot settings are unavailable.") from error

    raise UnsupportedActionError(f"Unsupported settings operation: {operation}")


def execute_reminder_operation(
    operation: str,
    action: ActionExecutionRequest,
    *,
    reminder_service: ReminderService | None = None,
) -> str:
    service = reminder_service or ReminderService()

    try:
        if operation == "create":
            minutes = validate_reminder_minutes(action.minutes)
            reminder_text = validate_reminder_text(action.query)
            service.create_reminder(minutes, reminder_text)
            return _format_reminder_created(minutes)

        if operation == "list":
            return service.format_pending_reminders()
    except ReminderStoreError as error:
        raise UnsupportedActionError(str(error)) from error

    raise UnsupportedActionError(f"Unsupported reminder operation: {operation}")


def validate_reminder_minutes(minutes: int | None) -> int:
    if minutes is None:
        raise UnsupportedActionError("Reminder minutes must be between 1 and 1440.")

    if minutes < 1 or minutes > 1440:
        raise UnsupportedActionError("Reminder minutes must be between 1 and 1440.")

    return minutes


def validate_reminder_text(reminder_text: str | None) -> str:
    if reminder_text is None or not reminder_text.strip():
        raise UnsupportedActionError("Reminder text must not be empty.")

    normalized_text = " ".join(reminder_text.split())
    if len(normalized_text) > MAX_REMINDER_TEXT_LENGTH:
        raise UnsupportedActionError("Reminder text is too long.")

    if any(_is_control_character(character) for character in reminder_text):
        raise UnsupportedActionError(
            "Reminder text contains unsupported control characters."
        )

    return normalized_text


def _format_reminder_created(minutes: int) -> str:
    if minutes == 1:
        return "Reminder set for 1 minute from now."

    return f"Reminder set for {minutes} minutes from now."


def execute_note_operation(
    operation: str,
    action: ActionExecutionRequest,
    *,
    note_store: NoteStore | None = None,
    launcher: ProcessLauncher | None = None,
) -> str:
    store = note_store or NoteStore()

    try:
        if operation == "create":
            note_text = validate_note_text(action.query)
            store.create_note(note_text)
            return "Note saved."

        if operation == "read_latest":
            return format_latest_note(store.read_latest_note())

        if operation == "count":
            return format_note_count(store.count_notes())

        if operation == "open_folder":
            notes_directory = store.ensure_directory()
            process_launcher = launcher or subprocess.Popen
            process_launcher(["explorer.exe", str(notes_directory)])
            return "Opening notes folder."
    except NoteStoreError as error:
        raise UnsupportedActionError(str(error)) from error
    except OSError as error:
        raise UnsupportedActionError("Local notes are unavailable.") from error

    raise UnsupportedActionError(f"Unsupported note operation: {operation}")


def validate_note_text(note_text: str | None) -> str:
    if note_text is None or not note_text.strip():
        raise UnsupportedActionError("Note text must not be empty.")

    normalized_text = " ".join(note_text.split())
    if len(normalized_text) > MAX_NOTE_TEXT_LENGTH:
        raise UnsupportedActionError("Note text is too long.")

    if any(_is_control_character(character) for character in note_text):
        raise UnsupportedActionError(
            "Note text contains unsupported control characters."
        )

    return normalized_text


def open_trusted_url(
    url: str,
    *,
    launcher: ProcessLauncher | None = None,
) -> None:
    process_launcher = launcher or subprocess.Popen
    process_launcher(["rundll32.exe", "url.dll,FileProtocolHandler", url])


def build_search_url(search_url: str, query: str) -> str:
    return f"{search_url}?{urlencode({'q': query})}"


def validate_search_query(query: str | None) -> str:
    if query is None or not query.strip():
        raise UnsupportedActionError("Search query must not be empty.")

    normalized_query = query.strip()
    if len(normalized_query) > MAX_SEARCH_QUERY_LENGTH:
        raise UnsupportedActionError("Search query is too long.")

    if any(_is_control_character(character) for character in normalized_query):
        raise UnsupportedActionError(
            "Search query contains unsupported control characters."
        )

    return normalized_query


def _is_control_character(character: str) -> bool:
    return ord(character) < 32 or ord(character) == 127


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
