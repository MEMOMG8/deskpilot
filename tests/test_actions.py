import json

import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.actions import (
    ActionExecutionError,
    KEYEVENTF_KEYUP,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    VK_VOLUME_DOWN,
    VK_VOLUME_MUTE,
    VK_VOLUME_UP,
    UnsupportedActionError,
    build_search_url,
    execute_action,
    format_battery_status,
    format_disk_status,
    format_memory_status,
)
from deskpilot_backend.main import (
    app,
    get_key_event_sender,
    get_note_store,
    get_process_launcher,
    get_reminder_service,
    get_settings_store,
    get_spotify_service,
    get_system_status_reader,
)
from deskpilot_backend.windows_media import MediaControlError, NO_SESSION_MESSAGE
from deskpilot_backend.models import ActionExecutionRequest
from deskpilot_backend.notes import NoteStore, format_latest_note, format_note_count
from deskpilot_backend.reminders import ReminderService
from deskpilot_backend.settings import SettingsStore, default_settings_data
from deskpilot_backend.spotify import SpotifyNoActiveDeviceError, SpotifyNotConnectedError
from deskpilot_backend.spotify import SpotifyDevice, SpotifyError


class RecordingLauncher:
    def __init__(self, events: list[str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.events = events

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
        if self.events is not None:
            self.events.append("launch")
        return object()


class RecordingKeyEventSender:
    def __init__(self) -> None:
        self.events: list[tuple[int, int]] = []

    def __call__(self, virtual_key: int, flags: int) -> object:
        self.events.append((virtual_key, flags))
        return object()


class RecordingSystemStatusReader:
    def __init__(self, messages: dict[str, str]) -> None:
        self.messages = messages
        self.targets: list[str] = []

    def __call__(self, target: str) -> str:
        self.targets.append(target)
        return self.messages[target]


class FakeSpotifyService:
    def __init__(
        self,
        play_results: list[object] | None = None,
        device_results: list[object] | None = None,
        transfer_results: list[object] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, object | None]] = []
        self.play_results = play_results or ["Playing Spotify."]
        self.device_results = device_results or [[]]
        self.transfer_results = transfer_results or ["Spotify playback transferred."]
        self.events = events

    def connect(self) -> str:
        self.calls.append(("connect", None))
        return "Spotify connected."

    def disconnect(self) -> str:
        self.calls.append(("disconnect", None))
        return "Spotify disconnected."

    def status(self) -> str:
        self.calls.append(("status", None))
        return "Spotify Playing: Test Song by Test Artist."

    def play(self) -> str:
        self.calls.append(("play", None))
        result = self.play_results.pop(0) if self.play_results else "Playing Spotify."
        if isinstance(result, Exception):
            raise result
        return str(result)

    def available_devices(self) -> list[SpotifyDevice]:
        self.calls.append(("devices", None))
        if self.events is not None:
            self.events.append("devices")
        result = self.device_results.pop(0) if self.device_results else []
        if isinstance(result, Exception):
            raise result
        return list(result)

    def transfer_playback(self, device_id: str, *, play: bool = True) -> str:
        self.calls.append(("transfer", (device_id, play)))
        result = (
            self.transfer_results.pop(0)
            if self.transfer_results
            else "Spotify playback transferred."
        )
        if isinstance(result, Exception):
            raise result
        return str(result)

    def pause(self) -> str:
        self.calls.append(("pause", None))
        return "Pausing Spotify."

    def next_track(self) -> str:
        self.calls.append(("next", None))
        return "Skipping to the next Spotify song."

    def previous_track(self) -> str:
        self.calls.append(("previous", None))
        return "Going to the previous Spotify song."

    def set_volume(self, volume_percent: int) -> str:
        self.calls.append(("volume", volume_percent))
        return f"Spotify volume set to {volume_percent}%."


class FakeTimer:
    def __init__(self, delay_seconds, callback) -> None:
        self.delay_seconds = delay_seconds
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeTimerFactory:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay_seconds, callback) -> FakeTimer:
        timer = FakeTimer(delay_seconds, callback)
        self.timers.append(timer)
        return timer


def spotify_device(
    device_id: str,
    *,
    device_type: str = "Computer",
    is_active: bool = False,
    is_restricted: bool = False,
) -> SpotifyDevice:
    return SpotifyDevice(
        id=device_id,
        name=f"Device {device_id}",
        type=device_type,
        is_active=is_active,
        is_restricted=is_restricted,
    )


@pytest.mark.parametrize(
    ("target", "expected_command", "expected_message"),
    [
        ("calculator", ["calc.exe"], "Opening Calculator."),
        ("notepad", ["notepad.exe"], "Opening Notepad."),
        ("file_explorer", ["explorer.exe"], "Opening File Explorer."),
        ("settings", ["explorer.exe", "ms-settings:"], "Opening Windows Settings."),
        (
            "browser",
            ["rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"],
            "Opening your default browser.",
        ),
        ("spotify", ["explorer.exe", "spotify:"], "Opening Spotify."),
    ],
)
def test_open_app_actions_are_allowed_with_fixed_commands(
    target: str,
    expected_command: list[str],
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target=target)

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands == [expected_command]


@pytest.mark.parametrize(
    ("target", "expected_url", "expected_message"),
    [
        ("google", "https://www.google.com/", "Opening Google."),
        ("youtube", "https://www.youtube.com/", "Opening YouTube."),
        ("github", "https://github.com/", "Opening GitHub."),
    ],
)
def test_fixed_site_actions_are_allowed_with_exact_https_urls(
    target: str,
    expected_url: str,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_url", target=target)

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands == [
        ["rundll32.exe", "url.dll,FileProtocolHandler", expected_url]
    ]


@pytest.mark.parametrize(
    ("target", "base_url", "expected_message"),
    [
        ("web", "https://www.google.com/search", "Searching the web for cats & dogs."),
        ("google", "https://www.google.com/search", "Searching Google for cats & dogs."),
        (
            "youtube",
            "https://www.youtube.com/results",
            "Searching YouTube for cats & dogs.",
        ),
        ("github", "https://github.com/search", "Searching GitHub for cats & dogs."),
    ],
)
def test_search_actions_encode_query_in_trusted_q_parameter(
    target: str,
    base_url: str,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(
        type="web_search",
        target=target,
        query="cats & dogs",
    )

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands == [
        [
            "rundll32.exe",
            "url.dll,FileProtocolHandler",
            f"{base_url}?q=cats+%26+dogs",
        ]
    ]


def test_build_search_url_uses_q_parameter_only() -> None:
    assert (
        build_search_url("https://github.com/search", "deskpilot python")
        == "https://github.com/search?q=deskpilot+python"
    )


@pytest.mark.parametrize(
    ("target", "virtual_key", "expected_message"),
    [
        ("volume_up", VK_VOLUME_UP, "Turning volume up."),
        ("volume_down", VK_VOLUME_DOWN, "Turning volume down."),
        ("mute", VK_VOLUME_MUTE, "Toggling mute."),
        ("play_pause", VK_MEDIA_PLAY_PAUSE, "Toggling media playback."),
    ],
)
def test_media_key_actions_are_allowed_with_fixed_key_events(
    target: str,
    virtual_key: int,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    action = ActionExecutionRequest(type="media_key", target=target)

    response = execute_action(
        action,
        launcher=launcher,
        key_event_sender=key_event_sender,
    )

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands == []
    assert key_event_sender.events == [(virtual_key, 0), (virtual_key, KEYEVENTF_KEYUP)]


@pytest.mark.parametrize(
    ("target", "expected_call", "expected_message"),
    [
        ("connect", ("connect", None), "Spotify connected."),
        ("disconnect", ("disconnect", None), "Spotify disconnected."),
        (
            "status",
            ("status", None),
            "Spotify Playing: Test Song by Test Artist.",
        ),
        ("play", ("play", None), "Playing Spotify."),
        ("pause", ("pause", None), "Pausing Spotify."),
        ("next", ("next", None), "Skipping to the next Spotify song."),
        ("previous", ("previous", None), "Going to the previous Spotify song."),
    ],
)
def test_spotify_actions_are_allowlisted_and_injected(
    target: str,
    expected_call: tuple[str, int | None],
    expected_message: str,
) -> None:
    service = FakeSpotifyService()
    action = ActionExecutionRequest(type="spotify", target=target)

    response = execute_action(action, spotify_service=service)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert service.calls == [expected_call]


def test_spotify_volume_action_validates_and_uses_fixed_service_method() -> None:
    service = FakeSpotifyService()
    action = ActionExecutionRequest(type="spotify", target="volume", query="75")

    response = execute_action(action, spotify_service=service)

    assert response.message == "Spotify volume set to 75%."
    assert service.calls == [("volume", 75)]


@pytest.mark.parametrize("query", [None, "", "loud", "-1", "101"])
def test_invalid_spotify_volume_action_is_rejected(query: str | None) -> None:
    service = FakeSpotifyService()

    with pytest.raises(
        UnsupportedActionError,
        match="Spotify volume must be between 0 and 100.",
    ):
        execute_action(
            ActionExecutionRequest(type="spotify", target="volume", query=query),
            spotify_service=service,
        )

    assert service.calls == []


def test_spotify_not_connected_and_no_active_device_are_user_friendly() -> None:
    class NotConnectedSpotify(FakeSpotifyService):
        def status(self) -> str:
            self.calls.append(("status", None))
            raise SpotifyNotConnectedError(
                "Spotify is not connected. Say connect spotify."
            )

    class NoDeviceSpotify(FakeSpotifyService):
        def play(self) -> str:
            self.calls.append(("play", None))
            raise SpotifyNoActiveDeviceError(
                "No active Spotify device. Open Spotify and play something first."
            )

    not_connected = NotConnectedSpotify()
    no_device = NoDeviceSpotify()

    with pytest.raises(ActionExecutionError, match="Spotify is not connected"):
        execute_action(
            ActionExecutionRequest(type="spotify", target="status"),
            spotify_service=not_connected,
        )
    with pytest.raises(ActionExecutionError, match="No active Spotify device"):
        execute_action(
            ActionExecutionRequest(type="spotify", target="play"),
            spotify_service=no_device,
        )


def test_default_music_is_local_without_oauth_tokens_or_http(tmp_path, monkeypatch, media_controller):
    import deskpilot_backend.spotify as spotify
    import urllib.request

    def forbidden(*args, **kwargs):
        pytest.fail("Public media must not construct Spotify services, read tokens or use HTTP")

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.setattr(spotify.SpotifyService, "__init__", forbidden)
    monkeypatch.setattr(spotify.DpapiSpotifyTokenStore, "load", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    launcher = RecordingLauncher()
    response = execute_action(
        ActionExecutionRequest(type="default_music", target="play"),
        launcher=launcher,
        settings_store=SettingsStore(tmp_path / "settings.json"),
        media_controller=media_controller,
    )
    assert response.executed is True
    assert response.message == "Playing the active Windows player."
    assert launcher.commands == [["explorer.exe", "spotify:"]]
    assert media_controller.calls == ["play"]


@pytest.mark.parametrize("target", ["pause", "next_track", "previous_track"])
def test_local_session_actions_are_allowlisted(target, media_controller):
    sender = RecordingKeyEventSender()
    response = execute_action(
        ActionExecutionRequest(type="media_key", target=target),
        media_controller=media_controller, key_event_sender=sender,
    )
    assert response.executed is True
    assert media_controller.calls == [target]
    assert sender.events == []


@pytest.mark.parametrize("action_type,target", [
    ("default_music", "play"), ("media_key", "pause"),
    ("media_key", "next_track"), ("media_key", "previous_track"),
])
def test_missing_session_does_not_return_executed(action_type, target, media_controller):
    media_controller.error = MediaControlError(NO_SESSION_MESSAGE)
    with pytest.raises(ActionExecutionError, match="No active Windows media session"):
        execute_action(
            ActionExecutionRequest(type=action_type, target=target),
            launcher=RecordingLauncher(), media_controller=media_controller,
        )


@pytest.mark.parametrize("action_type,target", [("open_app", "spotify"), ("default_music", "play")])
def test_spotify_launch_failure_is_not_success(action_type, target, media_controller):
    def failing_launcher(command):
        raise OSError("no handler")

    with pytest.raises(ActionExecutionError, match="couldn't open Spotify Desktop"):
        execute_action(
            ActionExecutionRequest(type=action_type, target=target),
            launcher=failing_launcher, media_controller=media_controller,
        )
    assert media_controller.calls == []


def test_failed_media_control_is_not_success(media_controller):
    media_controller.error = MediaControlError("The active Windows player rejected the command.")
    with pytest.raises(ActionExecutionError, match="rejected"):
        execute_action(
            ActionExecutionRequest(type="default_music", target="play"),
            launcher=RecordingLauncher(), media_controller=media_controller,
        )


def test_default_music_does_not_reopen_existing_spotify(media_controller):
    media_controller.spotify_open = True
    launcher = RecordingLauncher()
    execute_action(
        ActionExecutionRequest(type="default_music", target="play"),
        launcher=launcher, media_controller=media_controller,
    )
    assert launcher.commands == []
    assert media_controller.calls == ["play"]


def test_real_protocol_launcher_reports_missing_handler(monkeypatch):
    import deskpilot_backend.actions as actions

    def unavailable():
        raise OSError("protocol is missing")

    monkeypatch.setattr(actions, "_open_spotify_protocol", unavailable)
    with pytest.raises(ActionExecutionError, match="protocol registration"):
        execute_action(ActionExecutionRequest(type="open_app", target="spotify"))


@pytest.mark.parametrize(
    ("target", "expected_command", "expected_message"),
    [
        ("downloads", ["explorer.exe"], "Opening Downloads."),
        ("documents", ["explorer.exe"], "Opening Documents."),
        ("desktop", ["explorer.exe"], "Opening Desktop."),
        ("task_manager", ["taskmgr.exe"], "Opening Task Manager."),
    ],
)
def test_workspace_shortcuts_are_allowed_with_fixed_targets(
    target: str,
    expected_command: list[str],
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="workspace_shortcut", target=target)

    response = execute_action(action, launcher=launcher)

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert launcher.commands[0][0:1] == expected_command
    if target != "task_manager":
        assert len(launcher.commands[0]) == 2


@pytest.mark.parametrize(
    ("target", "expected_message"),
    [
        ("battery", "Battery is at 82%."),
        ("memory", "Memory usage is 47%."),
        ("disk", "Disk space is 123.4 GB available of 476.8 GB on C:."),
    ],
)
def test_system_status_actions_are_allowed_with_read_only_reader(
    target: str,
    expected_message: str,
) -> None:
    reader = RecordingSystemStatusReader(
        {
            "battery": "Battery is at 82%.",
            "memory": "Memory usage is 47%.",
            "disk": "Disk space is 123.4 GB available of 476.8 GB on C:.",
        }
    )
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    action = ActionExecutionRequest(type="system_status", target=target)

    response = execute_action(
        action,
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=reader,
    )

    assert response.executed is True
    assert response.status == "executed"
    assert response.action == action
    assert response.message == expected_message
    assert reader.targets == [target]
    assert launcher.commands == []
    assert key_event_sender.events == []


def test_status_formatters_return_concise_spoken_values() -> None:
    assert format_battery_status(82) == "Battery is at 82%."
    assert format_battery_status(None) == "No battery detected."
    assert format_memory_status(47) == "Memory usage is 47%."
    assert (
        format_disk_status(123.44, 476.82, "C:")
        == "Disk space is 123.4 GB available of 476.8 GB on C:."
    )


def test_note_create_action_writes_new_utf8_file_in_fixed_store(
    tmp_path,
) -> None:
    note_store = NoteStore(tmp_path / "notes")
    action = ActionExecutionRequest(type="note", target="create", query="Buy milk.")

    response = execute_action(action, note_store=note_store)

    note_files = list(note_store.notes_directory.glob("*.txt"))
    assert response.executed is True
    assert response.message == "Note saved."
    assert len(note_files) == 1
    assert note_files[0].parent == note_store.notes_directory
    assert note_files[0].read_text(encoding="utf-8") == "Buy milk.\n"


def test_note_create_action_never_overwrites_existing_note(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")

    execute_action(
        ActionExecutionRequest(type="note", target="create", query="First note."),
        note_store=note_store,
    )
    execute_action(
        ActionExecutionRequest(type="note", target="create", query="Second note."),
        note_store=note_store,
    )

    note_files = list(note_store.notes_directory.glob("*.txt"))
    assert len(note_files) == 2
    assert sorted(path.read_text(encoding="utf-8").strip() for path in note_files) == [
        "First note.",
        "Second note.",
    ]


def test_note_read_latest_action_reads_newest_note(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")

    execute_action(
        ActionExecutionRequest(type="note", target="create", query="Older note."),
        note_store=note_store,
    )
    execute_action(
        ActionExecutionRequest(type="note", target="create", query="Newest note."),
        note_store=note_store,
    )

    response = execute_action(
        ActionExecutionRequest(type="note", target="read_latest"),
        note_store=note_store,
    )

    assert response.message == "Latest note: Newest note."


def test_note_read_latest_action_handles_no_notes(tmp_path) -> None:
    response = execute_action(
        ActionExecutionRequest(type="note", target="read_latest"),
        note_store=NoteStore(tmp_path / "notes"),
    )

    assert response.message == "You do not have any notes yet."


def test_note_count_action_reports_count_only(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")
    execute_action(
        ActionExecutionRequest(type="note", target="create", query="One."),
        note_store=note_store,
    )

    response = execute_action(
        ActionExecutionRequest(type="note", target="count"),
        note_store=note_store,
    )

    assert response.message == "You have 1 note."


def test_note_open_folder_action_opens_only_store_directory(tmp_path) -> None:
    launcher = RecordingLauncher()
    note_store = NoteStore(tmp_path / "notes")

    response = execute_action(
        ActionExecutionRequest(type="note", target="open_folder"),
        launcher=launcher,
        note_store=note_store,
    )

    assert response.message == "Opening notes folder."
    assert launcher.commands == [["explorer.exe", str(note_store.notes_directory)]]
    assert note_store.notes_directory.exists()


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (None, "Note text must not be empty."),
        ("", "Note text must not be empty."),
        ("line\nbreak", "Note text contains unsupported control characters."),
        ("a" * 1001, "Note text is too long."),
    ],
)
def test_invalid_note_text_is_rejected_without_writing_file(
    tmp_path,
    query: str | None,
    message: str,
) -> None:
    note_store = NoteStore(tmp_path / "notes")

    with pytest.raises(UnsupportedActionError, match=message):
        execute_action(
            ActionExecutionRequest(type="note", target="create", query=query),
            note_store=note_store,
        )

    assert note_store.count_notes() == 0


def test_note_formatters_keep_latest_note_reasonably_short() -> None:
    long_note = "a" * 600

    assert format_latest_note(None) == "You do not have any notes yet."
    assert format_latest_note(long_note) == f"Latest note: {'a' * 500}..."
    assert format_note_count(0) == "You have 0 notes."
    assert format_note_count(2) == "You have 2 notes."


def test_open_deskpilot_settings_action_creates_file_and_opens_notepad(tmp_path) -> None:
    launcher = RecordingLauncher()
    settings_store = SettingsStore(tmp_path / "settings.json")
    action = ActionExecutionRequest(type="deskpilot_settings", target="open_file")

    response = execute_action(
        action,
        launcher=launcher,
        settings_store=settings_store,
    )

    assert response.executed is True
    assert response.message == "Opening DeskPilot settings."
    assert settings_store.settings_file.exists()
    assert json.loads(settings_store.settings_file.read_text(encoding="utf-8")) == (
        default_settings_data()
    )
    assert launcher.commands == [["notepad.exe", str(settings_store.settings_file)]]


def test_reminder_create_action_persists_and_schedules_temp_reminder(tmp_path) -> None:
    timers = FakeTimerFactory()
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=timers,
    )
    action = ActionExecutionRequest(
        type="reminder",
        target="create",
        minutes=5,
        query="Stretch.",
    )

    response = execute_action(action, reminder_service=reminder_service)

    assert response.executed is True
    assert response.message == "Reminder set for 5 minutes from now."
    assert len(reminder_service.list_pending_reminders()) == 1
    assert reminder_service.list_pending_reminders()[0].text == "Stretch."
    assert len(timers.timers) == 1


def test_reminder_list_action_reports_pending_reminders(tmp_path) -> None:
    timers = FakeTimerFactory()
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=timers,
    )
    reminder_service.create_reminder(1, "Soon.")

    response = execute_action(
        ActionExecutionRequest(type="reminder", target="list"),
        reminder_service=reminder_service,
    )

    assert response.message == "Pending reminders: in 1 minute, Soon.."


@pytest.mark.parametrize(
    ("minutes", "query", "message"),
    [
        (None, "Stretch.", "Reminder minutes must be between 1 and 1440."),
        (0, "Stretch.", "Reminder minutes must be between 1 and 1440."),
        (1441, "Stretch.", "Reminder minutes must be between 1 and 1440."),
        (5, "", "Reminder text must not be empty."),
        (5, "line\nbreak", "Reminder text contains unsupported control characters."),
        (5, "a" * 501, "Reminder text is too long."),
    ],
)
def test_invalid_reminder_action_is_rejected_without_scheduling(
    tmp_path,
    minutes: int | None,
    query: str,
    message: str,
) -> None:
    timers = FakeTimerFactory()
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=timers,
    )

    with pytest.raises(UnsupportedActionError, match=message):
        execute_action(
            ActionExecutionRequest(
                type="reminder",
                target="create",
                minutes=minutes,
                query=query,
            ),
            reminder_service=reminder_service,
        )

    assert reminder_service.list_pending_reminders() == []
    assert timers.timers == []


def test_media_key_rejects_unsupported_platform_without_succeeding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskpilot_backend.actions.sys.platform", "linux")
    action = ActionExecutionRequest(type="media_key", target="volume_up")

    with pytest.raises(
        UnsupportedActionError,
        match="Windows media controls are only supported on Windows.",
    ):
        execute_action(action)


def test_workspace_shortcut_rejects_unsupported_platform_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskpilot_backend.actions.sys.platform", "linux")
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="workspace_shortcut", target="downloads")

    with pytest.raises(
        UnsupportedActionError,
        match="Workspace shortcuts are only supported on Windows.",
    ):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_system_status_rejects_unsupported_platform_without_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskpilot_backend.actions.sys.platform", "linux")
    reader = RecordingSystemStatusReader({"battery": "Battery is at 82%."})
    action = ActionExecutionRequest(type="system_status", target="battery")

    with pytest.raises(
        UnsupportedActionError,
        match="System status commands are only supported on Windows.",
    ):
        execute_action(action, system_status_reader=reader)

    assert reader.targets == []


def test_unsupported_target_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_app", target="paint")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_media_target_is_rejected_and_never_sends_key_event() -> None:
    key_event_sender = RecordingKeyEventSender()
    action = ActionExecutionRequest(type="media_key", target="stop_music")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, key_event_sender=key_event_sender)

    assert key_event_sender.events == []


def test_unsupported_workspace_target_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="workspace_shortcut", target="pictures")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_status_target_is_rejected_and_never_reads_status() -> None:
    reader = RecordingSystemStatusReader({"cpu": "CPU usage is 5%."})
    action = ActionExecutionRequest(type="system_status", target="cpu")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, system_status_reader=reader)

    assert reader.targets == []


def test_unsupported_fixed_site_target_is_rejected_and_never_opens_browser() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="open_url", target="example")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_search_target_is_rejected_and_never_opens_browser() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="web_search", target="bing", query="deskpilot")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_note_target_is_rejected_and_never_writes_file(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")
    action = ActionExecutionRequest(type="note", target="delete")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, note_store=note_store)

    assert note_store.count_notes() == 0


def test_unsupported_reminder_target_is_rejected_and_never_schedules(tmp_path) -> None:
    timers = FakeTimerFactory()
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=timers,
    )
    action = ActionExecutionRequest(type="reminder", target="delete")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, reminder_service=reminder_service)

    assert reminder_service.list_pending_reminders() == []
    assert timers.timers == []


def test_unsupported_settings_target_is_rejected_and_never_opens_file(tmp_path) -> None:
    launcher = RecordingLauncher()
    settings_store = SettingsStore(tmp_path / "settings.json")
    action = ActionExecutionRequest(type="deskpilot_settings", target="delete")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, launcher=launcher, settings_store=settings_store)

    assert launcher.commands == []
    assert not settings_store.settings_file.exists()


def test_unsupported_spotify_target_is_rejected_without_service_call() -> None:
    service = FakeSpotifyService()
    action = ActionExecutionRequest(type="spotify", target="shuffle")

    with pytest.raises(UnsupportedActionError, match="Unsupported action target"):
        execute_action(action, spotify_service=service)

    assert service.calls == []


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (None, "Search query must not be empty."),
        ("", "Search query must not be empty."),
        ("line\nbreak", "Search query contains unsupported control characters."),
        ("a" * 121, "Search query is too long."),
    ],
)
def test_invalid_search_action_queries_are_rejected_without_opening_browser(
    query: str | None,
    message: str,
) -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="web_search", target="google", query=query)

    with pytest.raises(UnsupportedActionError, match=message):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_unsupported_action_type_is_rejected_and_never_launches_process() -> None:
    launcher = RecordingLauncher()
    action = ActionExecutionRequest(type="delete_file", target="calculator")

    with pytest.raises(UnsupportedActionError, match="Unsupported action type"):
        execute_action(action, launcher=launcher)

    assert launcher.commands == []


def test_actions_execute_endpoint_rejects_unsupported_action() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/actions/execute",
        json={"type": "open_app", "target": "paint"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported action target: paint"}


def test_actions_execute_endpoint_uses_mocked_media_key_sender() -> None:
    key_event_sender = RecordingKeyEventSender()
    client = TestClient(app)
    app.dependency_overrides[get_key_event_sender] = lambda: key_event_sender

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "media_key", "target": "mute"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Toggling mute."
    assert key_event_sender.events == [(VK_VOLUME_MUTE, 0), (VK_VOLUME_MUTE, KEYEVENTF_KEYUP)]


def test_actions_execute_endpoint_uses_mocked_system_status_reader() -> None:
    reader = RecordingSystemStatusReader({"battery": "No battery detected."})
    client = TestClient(app)
    app.dependency_overrides[get_system_status_reader] = lambda: reader

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "system_status", "target": "battery"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "No battery detected."
    assert reader.targets == ["battery"]


def test_actions_execute_endpoint_uses_mocked_browser_launcher() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)
    app.dependency_overrides[get_process_launcher] = lambda: launcher

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={
                "type": "web_search",
                "target": "google",
                "query": "deskpilot test",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Searching Google for deskpilot test."
    assert launcher.commands == [
        [
            "rundll32.exe",
            "url.dll,FileProtocolHandler",
            "https://www.google.com/search?q=deskpilot+test",
        ]
    ]


def test_actions_execute_endpoint_uses_temp_note_store(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")
    client = TestClient(app)
    app.dependency_overrides[get_note_store] = lambda: note_store

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "note", "target": "create", "query": "Local note."},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Note saved."
    assert note_store.count_notes() == 1


def test_actions_execute_endpoint_uses_temp_reminder_service(tmp_path) -> None:
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=FakeTimerFactory(),
    )
    client = TestClient(app)
    app.dependency_overrides[get_reminder_service] = lambda: reminder_service

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={
                "type": "reminder",
                "target": "create",
                "minutes": 5,
                "query": "Stretch.",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Reminder set for 5 minutes from now."
    assert len(reminder_service.list_pending_reminders()) == 1


def test_actions_execute_endpoint_uses_temp_settings_store(tmp_path) -> None:
    launcher = RecordingLauncher()
    settings_store = SettingsStore(tmp_path / "settings.json")
    client = TestClient(app)
    app.dependency_overrides[get_process_launcher] = lambda: launcher
    app.dependency_overrides[get_settings_store] = lambda: settings_store

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "deskpilot_settings", "target": "open_file"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Opening DeskPilot settings."
    assert settings_store.settings_file.exists()
    assert launcher.commands == [["notepad.exe", str(settings_store.settings_file)]]


def test_actions_execute_endpoint_uses_mocked_spotify_service() -> None:
    service = FakeSpotifyService()
    client = TestClient(app)
    app.dependency_overrides[get_spotify_service] = lambda: service

    try:
        response = client.post(
            "/api/v1/actions/execute",
            json={"type": "spotify", "target": "pause"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "Pausing Spotify."
    assert service.calls == [("pause", None)]
