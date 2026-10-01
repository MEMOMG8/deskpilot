import ctypes
import os
import subprocess
import sys
import time
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
from deskpilot_backend.spotify import (
    SpotifyDevice,
    SpotifyError,
    SpotifyNoActiveDeviceError,
    SpotifyNotConnectedError,
    SpotifyOAuthError,
    SpotifyService,
)

OPEN_APP_ACTION_TYPE = "open_app"
MEDIA_KEY_ACTION_TYPE = "media_key"
WORKSPACE_SHORTCUT_ACTION_TYPE = "workspace_shortcut"
SYSTEM_STATUS_ACTION_TYPE = "system_status"
OPEN_URL_ACTION_TYPE = "open_url"
WEB_SEARCH_ACTION_TYPE = "web_search"
NOTE_ACTION_TYPE = "note"
REMINDER_ACTION_TYPE = "reminder"
DESKPILOT_SETTINGS_ACTION_TYPE = "deskpilot_settings"
SPOTIFY_ACTION_TYPE = "spotify"
DEFAULT_MUSIC_ACTION_TYPE = "default_music"
MAX_SEARCH_QUERY_LENGTH = 120
DEFAULT_MUSIC_APP = "spotify"
SPOTIFY_APP_COMMAND = ("explorer.exe", "spotify:")
SPOTIFY_ACTIVE_DEVICE_WAIT_SECONDS = 8.0
SPOTIFY_ACTIVE_DEVICE_POLL_SECONDS = 0.5
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
SleepFunction = Callable[[float], object]


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
    spotify_operation: str | None = None
    default_music_operation: str | None = None
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
    (OPEN_APP_ACTION_TYPE, "spotify"): ActionDefinition(
        action_type=OPEN_APP_ACTION_TYPE,
        command=SPOTIFY_APP_COMMAND,
        message="Opening Spotify.",
        unsupported_platform_message="Spotify launch is only supported on Windows.",
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
    (SPOTIFY_ACTION_TYPE, "connect"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="connect",
        message="Connecting Spotify.",
    ),
    (SPOTIFY_ACTION_TYPE, "disconnect"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="disconnect",
        message="Disconnecting Spotify.",
    ),
    (SPOTIFY_ACTION_TYPE, "status"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="status",
        message="Checking Spotify.",
    ),
    (SPOTIFY_ACTION_TYPE, "play"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="play",
        message="Playing Spotify.",
    ),
    (SPOTIFY_ACTION_TYPE, "pause"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="pause",
        message="Pausing Spotify.",
    ),
    (SPOTIFY_ACTION_TYPE, "next"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="next",
        message="Skipping Spotify.",
    ),
    (SPOTIFY_ACTION_TYPE, "previous"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="previous",
        message="Going to previous Spotify song.",
    ),
    (SPOTIFY_ACTION_TYPE, "volume"): ActionDefinition(
        action_type=SPOTIFY_ACTION_TYPE,
        spotify_operation="volume",
        message="Setting Spotify volume.",
    ),
    (DEFAULT_MUSIC_ACTION_TYPE, "play"): ActionDefinition(
        action_type=DEFAULT_MUSIC_ACTION_TYPE,
        default_music_operation="play",
        message="Playing music.",
        unsupported_platform_message="Default music playback is only supported on Windows.",
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
    spotify_service: SpotifyService | None = None,
    sleeper: SleepFunction | None = None,
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
    elif action_definition.spotify_operation is not None:
        message = execute_spotify_operation(
            action_definition.spotify_operation,
            action,
            spotify_service=spotify_service,
        )
    elif action_definition.default_music_operation is not None:
        message = execute_default_music_operation(
            action_definition.default_music_operation,
            launcher=launcher,
            spotify_service=spotify_service,
            settings_store=settings_store,
            sleeper=sleeper,
        )

    return ActionExecutionResponse(
        status="executed",
        executed=True,
        action=action,
        message=message,
    )


def execute_spotify_operation(
    operation: str,
    action: ActionExecutionRequest,
    *,
    spotify_service: SpotifyService | None = None,
) -> str:
    service = spotify_service or SpotifyService()
    try:
        if operation == "connect":
            return service.connect()
        if operation == "disconnect":
            return service.disconnect()
        if operation == "status":
            return service.status()
        if operation == "play":
            return service.play()
        if operation == "pause":
            return service.pause()
        if operation == "next":
            return service.next_track()
        if operation == "previous":
            return service.previous_track()
        if operation == "volume":
            return service.set_volume(validate_spotify_volume(action.query))
    except (SpotifyNotConnectedError, SpotifyNoActiveDeviceError) as error:
        return str(error)
    except SpotifyOAuthError as error:
        return str(error)
    except SpotifyError as error:
        raise UnsupportedActionError(str(error)) from error

    raise UnsupportedActionError(f"Unsupported Spotify operation: {operation}")


def execute_default_music_operation(
    operation: str,
    *,
    launcher: ProcessLauncher | None = None,
    spotify_service: SpotifyService | None = None,
    settings_store: SettingsStore | None = None,
    sleeper: SleepFunction | None = None,
) -> str:
    if operation != "play":
        raise UnsupportedActionError(f"Unsupported default music operation: {operation}")

    if _load_default_music_app(settings_store) != DEFAULT_MUSIC_APP:
        raise UnsupportedActionError("Default music app is not supported.")

    service = spotify_service or SpotifyService()
    known_device_ids: set[str] = set()
    prelaunch_message: str | None = None
    try:
        known_device_ids = {device.id for device in service.available_devices()}
    except SpotifyNotConnectedError:
        prelaunch_message = (
            "Spotify is not connected. Say connect spotify to enable voice playback."
        )
    except (SpotifyOAuthError, SpotifyError):
        prelaunch_message = "Spotify playback is unavailable."

    launch_message = launch_spotify(launcher=launcher)
    if launch_message is not None:
        return launch_message

    if prelaunch_message is not None:
        return prelaunch_message

    return play_spotify_after_launch(
        spotify_service=service,
        known_device_ids=known_device_ids,
        sleeper=sleeper,
    )


def launch_spotify(*, launcher: ProcessLauncher | None = None) -> str | None:
    process_launcher = launcher or subprocess.Popen
    try:
        process_launcher(list(SPOTIFY_APP_COMMAND))
    except OSError:
        return "I couldn't open Spotify."

    return None


def play_spotify_after_launch(
    *,
    spotify_service: SpotifyService,
    known_device_ids: set[str],
    sleeper: SleepFunction | None = None,
) -> str:
    service = spotify_service
    sleep = sleeper or time.sleep
    attempts = max(
        1,
        int(SPOTIFY_ACTIVE_DEVICE_WAIT_SECONDS / SPOTIFY_ACTIVE_DEVICE_POLL_SECONDS)
        + 1,
    )

    for attempt in range(attempts):
        try:
            current_devices = service.available_devices()
            target_device = select_spotify_desktop_device(
                known_device_ids,
                current_devices,
            )
            if target_device is not None:
                service.transfer_playback(target_device.id, play=True)
                return "Opening Spotify and playing music."
        except SpotifyNotConnectedError:
            return "Spotify is not connected. Say connect spotify to enable voice playback."
        except (SpotifyOAuthError, SpotifyError):
            return "Spotify playback is unavailable."

        if attempt < attempts - 1:
            sleep(SPOTIFY_ACTIVE_DEVICE_POLL_SECONDS)
            continue

        return "Spotify is open. Start a song there once, then I can control it."

    return "Spotify is open. Start a song there once, then I can control it."


def select_spotify_desktop_device(
    known_device_ids: set[str],
    devices: Sequence[SpotifyDevice],
) -> SpotifyDevice | None:
    eligible_devices = [device for device in devices if is_eligible_spotify_desktop(device)]

    newly_available = [
        device for device in eligible_devices if device.id not in known_device_ids
    ]
    if len(newly_available) == 1:
        return _spotify_device_if_not_transferring_from_active_device(
            newly_available[0],
            devices,
        )

    if len(newly_available) > 1:
        return None

    if len(eligible_devices) == 1:
        return _spotify_device_if_not_transferring_from_active_device(
            eligible_devices[0],
            devices,
        )

    return None


def is_eligible_spotify_desktop(device: SpotifyDevice) -> bool:
    return (
        bool(device.id)
        and device.type.casefold() == "computer"
        and not device.is_restricted
    )


def _spotify_device_if_not_transferring_from_active_device(
    candidate: SpotifyDevice,
    devices: Sequence[SpotifyDevice],
) -> SpotifyDevice | None:
    if any(device.is_active and device.id != candidate.id for device in devices):
        return None

    return candidate


def _load_default_music_app(settings_store: SettingsStore | None) -> str:
    if settings_store is None:
        return DEFAULT_MUSIC_APP

    try:
        return settings_store.load_or_create().default_music_app
    except Exception:
        return DEFAULT_MUSIC_APP


def validate_spotify_volume(raw_volume: str | None) -> int:
    if raw_volume is None or not raw_volume.isdecimal():
        raise UnsupportedActionError("Spotify volume must be between 0 and 100.")
    volume = int(raw_volume)
    if volume < 0 or volume > 100:
        raise UnsupportedActionError("Spotify volume must be between 0 and 100.")
    return volume


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
