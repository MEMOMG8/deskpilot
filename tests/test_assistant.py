from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from deskpilot_backend.actions import KEYEVENTF_KEYUP, VK_MEDIA_PLAY_PAUSE, VK_VOLUME_UP
from deskpilot_backend.assistant import handle_assistant_command
from deskpilot_backend.command_interpreter import (
    ClarificationStore,
    CommandInterpretation,
    CommandInterpreterError,
)
from deskpilot_backend.commands import HELP_MESSAGE
from deskpilot_backend.models import AssistantCommandRequest
from deskpilot_backend.main import (
    app,
    get_key_event_sender,
    get_note_store,
    get_process_launcher,
    get_reminder_service,
    get_settings_store,
    get_speech_engine_factory,
    get_system_status_reader,
)
from deskpilot_backend.notes import NoteStore
from deskpilot_backend.reminders import ReminderService
from deskpilot_backend.settings import SettingsStore


class RecordingLauncher:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> object:
        self.commands.append(command)
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


class FakeTimer:
    def __init__(self, delay_seconds, callback) -> None:
        self.delay_seconds = delay_seconds
        self.callback = callback

    def cancel(self) -> None:
        return None


class FakeTimerFactory:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay_seconds, callback) -> FakeTimer:
        timer = FakeTimer(delay_seconds, callback)
        self.timers.append(timer)
        return timer


class FakeSpeechEngine:
    def __init__(self) -> None:
        self.spoken_text: list[str] = []
        self.completed = False

    def say(self, text: str) -> None:
        self.spoken_text.append(text)

    def runAndWait(self) -> None:
        self.completed = True


class FakeCommandInterpreter:
    def __init__(self, interpretation: CommandInterpretation | None = None) -> None:
        self.interpretation = interpretation or CommandInterpretation(unknown=True)
        self.calls: list[str] = []

    def interpret(self, transcript: str) -> CommandInterpretation:
        self.calls.append(transcript)
        return self.interpretation


class FailingCommandInterpreter(FakeCommandInterpreter):
    def interpret(self, transcript: str) -> CommandInterpretation:
        self.calls.append(transcript)
        raise CommandInterpreterError("Natural-language command understanding failed.")


@contextmanager
def mocked_dependencies(
    launcher: RecordingLauncher | None = None,
    key_event_sender: RecordingKeyEventSender | None = None,
    system_status_reader: RecordingSystemStatusReader | None = None,
    note_store: NoteStore | None = None,
    reminder_service: ReminderService | None = None,
    settings_store: SettingsStore | None = None,
    speech_engine_factory: object | None = None,
) -> Iterator[None]:
    if launcher is not None:
        app.dependency_overrides[get_process_launcher] = lambda: launcher

    if key_event_sender is not None:
        app.dependency_overrides[get_key_event_sender] = lambda: key_event_sender

    if system_status_reader is not None:
        app.dependency_overrides[get_system_status_reader] = (
            lambda: system_status_reader
        )

    if note_store is not None:
        app.dependency_overrides[get_note_store] = lambda: note_store

    if reminder_service is not None:
        app.dependency_overrides[get_reminder_service] = lambda: reminder_service

    if settings_store is not None:
        app.dependency_overrides[get_settings_store] = lambda: settings_store

    if speech_engine_factory is not None:
        app.dependency_overrides[get_speech_engine_factory] = (
            lambda: speech_engine_factory
        )

    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_assistant_open_calculator_routes_and_executes_successfully() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Opening Calculator.",
        "speech_result": "not_requested",
        "action": {"type": "open_app", "target": "calculator"},
    }


def test_assistant_process_launcher_is_mocked_for_calculator() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator"},
        )

    assert launcher.commands == [["calc.exe"]]


@pytest.mark.parametrize(
    ("text", "target", "expected_command", "expected_message"),
    [
        ("open notepad", "notepad", ["notepad.exe"], "Opening Notepad."),
        ("open file explorer", "file_explorer", ["explorer.exe"], "Opening File Explorer."),
        ("open explorer", "file_explorer", ["explorer.exe"], "Opening File Explorer."),
        ("open settings", "settings", ["explorer.exe", "ms-settings:"], "Opening Windows Settings."),
        (
            "open browser",
            "browser",
            ["rundll32.exe", "url.dll,FileProtocolHandler", "https://example.com"],
            "Opening your default browser.",
        ),
    ],
)
def test_assistant_app_commands_route_and_execute(
    text: str,
    target: str,
    expected_command: list[str],
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "open_app", "target": target},
    }
    assert launcher.commands == [expected_command]


def test_assistant_help_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post("/api/v1/assistant/commands", json={"text": "help"})

    assert response.status_code == 200
    assert response.json() == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": HELP_MESSAGE,
        "speech_result": "not_requested",
    }
    assert launcher.commands == []


def test_assistant_unknown_command_does_not_call_executor() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open paint"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "unknown",
        "status": "not_supported",
        "requires_confirmation": False,
        "message": "That command is not supported yet.",
        "speech_result": "not_requested",
    }
    assert launcher.commands == []


@pytest.mark.parametrize("text", ["cancel", "never mind"])
def test_assistant_cancel_commands_do_not_call_executor(text: str) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "cancel",
        "status": "completed",
        "requires_confirmation": False,
        "message": "Cancelled.",
        "speech_result": "not_requested",
    }
    assert launcher.commands == []


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("what time is it", "get_time"),
        ("what's the time", "get_time"),
        ("what is the date", "get_date"),
        ("what's today's date", "get_date"),
        ("what can you do", "help"),
    ],
)
def test_assistant_information_commands_do_not_call_executor(
    text: str,
    intent: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json()["intent"] == intent
    assert response.json()["status"] == "completed"
    assert launcher.commands == []


@pytest.mark.parametrize(
    ("text", "target", "virtual_key", "expected_message"),
    [
        ("volume up", "volume_up", VK_VOLUME_UP, "Turning volume up."),
        ("turn volume up", "volume_up", VK_VOLUME_UP, "Turning volume up."),
        ("play music", "play_pause", VK_MEDIA_PLAY_PAUSE, "Toggling media playback."),
        ("pause music", "play_pause", VK_MEDIA_PLAY_PAUSE, "Toggling media playback."),
    ],
)
def test_assistant_media_commands_route_and_send_fixed_key_events(
    text: str,
    target: str,
    virtual_key: int,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, key_event_sender=key_event_sender):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "media_control",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "media_key", "target": target},
    }
    assert launcher.commands == []
    assert key_event_sender.events == [(virtual_key, 0), (virtual_key, KEYEVENTF_KEYUP)]


@pytest.mark.parametrize(
    ("text", "target", "expected_url", "expected_message"),
    [
        ("open google", "google", "https://www.google.com/", "Opening Google."),
        ("open youtube", "youtube", "https://www.youtube.com/", "Opening YouTube."),
        ("open github", "github", "https://github.com/", "Opening GitHub."),
    ],
)
def test_assistant_fixed_site_commands_open_allowlisted_urls(
    text: str,
    target: str,
    expected_url: str,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_site",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "open_url", "target": target},
    }
    assert launcher.commands == [
        ["rundll32.exe", "url.dll,FileProtocolHandler", expected_url]
    ]


@pytest.mark.parametrize(
    ("text", "target", "expected_url", "expected_message"),
    [
        (
            "search web for cats & dogs",
            "web",
            "https://www.google.com/search?q=cats+%26+dogs",
            "Searching the web for cats & dogs.",
        ),
        (
            "search google for cats & dogs",
            "google",
            "https://www.google.com/search?q=cats+%26+dogs",
            "Searching Google for cats & dogs.",
        ),
        (
            "search youtube for cats & dogs",
            "youtube",
            "https://www.youtube.com/results?q=cats+%26+dogs",
            "Searching YouTube for cats & dogs.",
        ),
        (
            "search github for cats & dogs",
            "github",
            "https://github.com/search?q=cats+%26+dogs",
            "Searching GitHub for cats & dogs.",
        ),
    ],
)
def test_assistant_search_commands_open_encoded_search_urls(
    text: str,
    target: str,
    expected_url: str,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "web_search",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "web_search", "target": target, "query": "cats & dogs"},
    }
    assert launcher.commands == [
        ["rundll32.exe", "url.dll,FileProtocolHandler", expected_url]
    ]


def test_assistant_rejects_invalid_search_query() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/assistant/commands",
        json={"text": "search google for"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Search query must not be empty."}


@pytest.mark.parametrize(
    ("text", "target", "expected_message"),
    [
        ("open downloads", "downloads", "Opening Downloads."),
        ("open documents", "documents", "Opening Documents."),
        ("open desktop", "desktop", "Opening Desktop."),
        ("open task manager", "task_manager", "Opening Task Manager."),
    ],
)
def test_assistant_workspace_commands_route_and_execute(
    text: str,
    target: str,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "workspace_shortcut",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "workspace_shortcut", "target": target},
    }
    assert launcher.commands != []


@pytest.mark.parametrize(
    ("text", "target", "expected_message"),
    [
        ("battery status", "battery", "No battery detected."),
        ("what is my battery level", "battery", "No battery detected."),
        ("memory status", "memory", "Memory usage is 47%."),
        ("how much memory am I using", "memory", "Memory usage is 47%."),
        (
            "disk space",
            "disk",
            "Disk space is 123.4 GB available of 476.8 GB on C:.",
        ),
        (
            "how much disk space do I have",
            "disk",
            "Disk space is 123.4 GB available of 476.8 GB on C:.",
        ),
    ],
)
def test_assistant_system_status_commands_route_and_read_status(
    text: str,
    target: str,
    expected_message: str,
) -> None:
    launcher = RecordingLauncher()
    key_event_sender = RecordingKeyEventSender()
    reader = RecordingSystemStatusReader(
        {
            "battery": "No battery detected.",
            "memory": "Memory usage is 47%.",
            "disk": "Disk space is 123.4 GB available of 476.8 GB on C:.",
        }
    )
    client = TestClient(app)

    with mocked_dependencies(
        launcher=launcher,
        key_event_sender=key_event_sender,
        system_status_reader=reader,
    ):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": text},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "system_status",
        "status": "executed",
        "requires_confirmation": False,
        "message": expected_message,
        "speech_result": "not_requested",
        "action": {"type": "system_status", "target": target},
    }
    assert reader.targets == [target]
    assert launcher.commands == []
    assert key_event_sender.events == []


def test_assistant_note_create_saves_to_temp_store(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")
    client = TestClient(app)

    with mocked_dependencies(note_store=note_store):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "take a note Buy milk"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "notes",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Note saved.",
        "speech_result": "not_requested",
        "action": {"type": "note", "target": "create", "query": "Buy milk"},
    }
    assert note_store.count_notes() == 1


def test_assistant_note_read_count_and_open_folder_use_temp_store(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")
    launcher = RecordingLauncher()
    client = TestClient(app)

    note_store.create_note("Remember the demo.")

    with mocked_dependencies(launcher=launcher, note_store=note_store):
        latest = client.post(
            "/api/v1/assistant/commands",
            json={"text": "read latest note"},
        )
        count = client.post(
            "/api/v1/assistant/commands",
            json={"text": "how many notes do I have"},
        )
        folder = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open notes folder"},
        )

    assert latest.status_code == 200
    assert latest.json()["message"] == "Latest note: Remember the demo."
    assert count.status_code == 200
    assert count.json()["message"] == "You have 1 note."
    assert folder.status_code == 200
    assert folder.json()["message"] == "Opening notes folder."
    assert launcher.commands == [["explorer.exe", str(note_store.notes_directory)]]


def test_assistant_note_read_latest_handles_empty_store(tmp_path) -> None:
    client = TestClient(app)

    with mocked_dependencies(note_store=NoteStore(tmp_path / "notes")):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "read latest note"},
        )

    assert response.status_code == 200
    assert response.json()["message"] == "You do not have any notes yet."


def test_assistant_open_deskpilot_settings_uses_fixed_settings_file(tmp_path) -> None:
    launcher = RecordingLauncher()
    settings_store = SettingsStore(tmp_path / "settings.json")
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, settings_store=settings_store):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open deskpilot settings"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "settings",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Opening DeskPilot settings.",
        "speech_result": "not_requested",
        "action": {"type": "deskpilot_settings", "target": "open_file"},
    }
    assert launcher.commands == [["notepad.exe", str(settings_store.settings_file)]]


def test_assistant_note_with_speak_narrates_existing_tts_response(tmp_path) -> None:
    note_store = NoteStore(tmp_path / "notes")
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_dependencies(
        note_store=note_store,
        speech_engine_factory=lambda: engine,
    ):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "note Read this aloud", "speak": True},
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Note saved."
    assert response.json()["speech_result"] == "completed"
    assert engine.spoken_text == ["Note saved."]


def test_assistant_rejects_invalid_note_text() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/assistant/commands",
        json={"text": "take a note"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Note text must not be empty."}


def test_assistant_reminder_create_schedules_with_temp_service(tmp_path) -> None:
    timers = FakeTimerFactory()
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=timers,
    )
    client = TestClient(app)

    with mocked_dependencies(reminder_service=reminder_service):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "remind me in 5 minutes to Stretch"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "reminders",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Reminder set for 5 minutes from now.",
        "speech_result": "not_requested",
        "action": {
            "type": "reminder",
            "target": "create",
            "query": "Stretch",
            "minutes": 5,
        },
    }
    assert len(reminder_service.list_pending_reminders()) == 1
    assert len(timers.timers) == 1


def test_assistant_reminder_list_reports_pending_reminders(tmp_path) -> None:
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=FakeTimerFactory(),
    )
    reminder_service.create_reminder(1, "Soon.")
    client = TestClient(app)

    with mocked_dependencies(reminder_service=reminder_service):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "list reminders"},
        )

    assert response.status_code == 200
    assert response.json()["intent"] == "reminders"
    assert response.json()["message"] == "Pending reminders: in 1 minute, Soon.."


def test_assistant_reminder_with_speak_narrates_confirmation(tmp_path) -> None:
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=FakeTimerFactory(),
    )
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_dependencies(
        reminder_service=reminder_service,
        speech_engine_factory=lambda: engine,
    ):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "remind me in 1 minutes to Stretch", "speak": True},
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Reminder set for 1 minute from now."
    assert response.json()["speech_result"] == "completed"
    assert engine.spoken_text == ["Reminder set for 1 minute from now."]


def test_assistant_rejects_invalid_reminder() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/assistant/commands",
        json={"text": "remind me in 0 minutes to Stretch"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Reminder minutes must be between 1 and 1440."
    }


def test_assistant_blank_input_is_rejected() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/assistant/commands", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, text must not be empty"


def test_assistant_speak_omitted_or_false_does_not_call_speech_service() -> None:
    client = TestClient(app)

    def speech_service_must_not_run() -> FakeSpeechEngine:
        raise AssertionError("speech service should not run")

    with mocked_dependencies(speech_engine_factory=speech_service_must_not_run):
        omitted_response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "help"},
        )
        false_response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "help", "speak": False},
        )

    assert omitted_response.status_code == 200
    assert omitted_response.json()["speech_result"] == "not_requested"
    assert false_response.status_code == 200
    assert false_response.json()["speech_result"] == "not_requested"


def test_assistant_open_calculator_with_speak_executes_and_narrates() -> None:
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, speech_engine_factory=lambda: engine):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator", "speak": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Opening Calculator.",
        "speech_result": "completed",
        "action": {"type": "open_app", "target": "calculator"},
    }
    assert launcher.commands == [["calc.exe"]]
    assert engine.spoken_text == ["Opening Calculator."]
    assert engine.completed is True


def test_assistant_help_with_speak_narrates_without_executing_app() -> None:
    launcher = RecordingLauncher()
    engine = FakeSpeechEngine()
    client = TestClient(app)

    with mocked_dependencies(launcher=launcher, speech_engine_factory=lambda: engine):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "help", "speak": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "help",
        "status": "completed",
        "requires_confirmation": False,
        "message": HELP_MESSAGE,
        "speech_result": "completed",
    }
    assert launcher.commands == []
    assert engine.spoken_text == [HELP_MESSAGE]


def test_assistant_speech_failure_does_not_change_command_result() -> None:
    launcher = RecordingLauncher()
    client = TestClient(app)

    def unavailable_speech_engine() -> FakeSpeechEngine:
        raise RuntimeError("speech unavailable")

    with mocked_dependencies(
        launcher=launcher,
        speech_engine_factory=unavailable_speech_engine,
    ):
        response = client.post(
            "/api/v1/assistant/commands",
            json={"text": "open calculator", "speak": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "intent": "open_app",
        "status": "executed",
        "requires_confirmation": False,
        "message": "Opening Calculator.",
        "speech_result": "unavailable",
        "action": {"type": "open_app", "target": "calculator"},
    }
    assert launcher.commands == [["calc.exe"]]


def test_exact_command_bypasses_cloud_interpreter(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    launcher = RecordingLauncher()
    interpreter = FakeCommandInterpreter(CommandInterpretation(command_text="open notepad"))

    response = handle_assistant_command(
        AssistantCommandRequest(text="open calculator"),
        launcher=launcher,
        command_interpreter=interpreter,
        command_interpreter_provider="openai",
    )

    assert response.message == "Opening Calculator."
    assert launcher.commands == [["calc.exe"]]
    assert interpreter.calls == []


def test_natural_language_fixed_command_executes_through_local_allowlist(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    launcher = RecordingLauncher()
    interpreter = FakeCommandInterpreter(
        CommandInterpretation(command_text="open notepad")
    )

    response = handle_assistant_command(
        AssistantCommandRequest(text="Could you please open Notepad for me?"),
        launcher=launcher,
        command_interpreter=interpreter,
        command_interpreter_provider="openai",
    )

    assert response.intent == "open_app"
    assert response.status == "executed"
    assert response.message == "Opening Notepad."
    assert launcher.commands == [["notepad.exe"]]
    assert interpreter.calls == ["Could you please open Notepad for me?"]


def test_natural_language_note_reminder_and_search_use_existing_validation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    note_store = NoteStore(tmp_path / "notes")
    reminder_service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=FakeTimerFactory(),
    )
    launcher = RecordingLauncher()

    note_response = handle_assistant_command(
        AssistantCommandRequest(text="Remember that milk is low"),
        note_store=note_store,
        command_interpreter=FakeCommandInterpreter(
            CommandInterpretation(command_text="note Buy milk")
        ),
        command_interpreter_provider="openai",
    )
    reminder_response = handle_assistant_command(
        AssistantCommandRequest(text="Remind me to stretch soon"),
        reminder_service=reminder_service,
        command_interpreter=FakeCommandInterpreter(
            CommandInterpretation(command_text="remind me in 5 minutes to Stretch")
        ),
        command_interpreter_provider="openai",
    )
    search_response = handle_assistant_command(
        AssistantCommandRequest(text="Find FastAPI examples on GitHub"),
        launcher=launcher,
        command_interpreter=FakeCommandInterpreter(
            CommandInterpretation(command_text="search github for fastapi examples")
        ),
        command_interpreter_provider="openai",
    )

    assert note_response.message == "Note saved."
    assert note_store.count_notes() == 1
    assert reminder_response.message == "Reminder set for 5 minutes from now."
    assert len(reminder_service.list_pending_reminders()) == 1
    assert search_response.message == "Searching GitHub for fastapi examples."
    assert launcher.commands == [
        [
            "rundll32.exe",
            "url.dll,FileProtocolHandler",
            "https://github.com/search?q=fastapi+examples",
        ]
    ]


def test_invalid_interpreted_payload_falls_back_to_unknown(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    response = handle_assistant_command(
        AssistantCommandRequest(text="Make a private note"),
        command_interpreter=FakeCommandInterpreter(
            CommandInterpretation(command_text="note \x01")
        ),
        command_interpreter_provider="openai",
    )

    assert response.intent == "unknown"
    assert response.status == "not_supported"
    assert response.message == "That command is not supported yet."


def test_unknown_openai_failure_missing_key_and_local_only_modes(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    failing = FailingCommandInterpreter()

    failure_response = handle_assistant_command(
        AssistantCommandRequest(text="Please do something unsupported"),
        command_interpreter=failing,
        command_interpreter_provider="openai",
    )
    assert failure_response.intent == "unknown"
    assert failing.calls == ["Please do something unsupported"]

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    missing_key_messages: list[str] = []
    missing_key_response = handle_assistant_command(
        AssistantCommandRequest(text="Please open the notes app"),
        command_interpreter=FakeCommandInterpreter(
            CommandInterpretation(command_text="open notepad")
        ),
        command_interpreter_provider="openai",
        on_recoverable_error=missing_key_messages.append,
    )
    assert missing_key_response.message == (
        "Natural-language command understanding needs OPENAI_API_KEY."
    )
    assert missing_key_messages == [
        "Natural-language command understanding needs OPENAI_API_KEY."
    ]

    local_interpreter = FakeCommandInterpreter(
        CommandInterpretation(command_text="open notepad")
    )
    local_response = handle_assistant_command(
        AssistantCommandRequest(text="Please open Notepad"),
        command_interpreter=local_interpreter,
        command_interpreter_provider="local",
    )
    assert local_response.message == "That command is not supported yet."
    assert local_interpreter.calls == []


def test_assistant_clarification_question_and_replies(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    store = ClarificationStore()
    launcher = RecordingLauncher()
    interpreter = FakeCommandInterpreter(
        CommandInterpretation(
            clarification_question="Did you mean Notepad or Calculator?",
            clarification_candidates=("open notepad", "open calculator"),
        )
    )

    question = handle_assistant_command(
        AssistantCommandRequest(text="Open the app"),
        command_interpreter=interpreter,
        command_interpreter_provider="openai",
        clarification_store=store,
    )
    first = handle_assistant_command(
        AssistantCommandRequest(text="first option"),
        launcher=launcher,
        clarification_store=store,
    )

    assert question.requires_confirmation is True
    assert question.message == "Did you mean Notepad or Calculator?"
    assert first.message == "Opening Notepad."
    assert launcher.commands == [["notepad.exe"]]

    store.set(["open notepad", "open calculator"])
    second = handle_assistant_command(
        AssistantCommandRequest(text="second option"),
        launcher=launcher,
        clarification_store=store,
    )
    assert second.message == "Opening Calculator."

    store.set(["open notepad"])
    cancel = handle_assistant_command(
        AssistantCommandRequest(text="never mind"),
        launcher=launcher,
        clarification_store=store,
    )
    assert cancel.message == "Cancelled."

    store.set(["open notepad"])
    unrelated = handle_assistant_command(
        AssistantCommandRequest(text="open calculator"),
        launcher=launcher,
        clarification_store=store,
    )
    assert unrelated.message == "Opening Calculator."
