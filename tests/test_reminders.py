import json
from datetime import UTC, datetime, timedelta

from deskpilot_backend.reminders import ReminderService


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


class ManualClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 23, 18, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_reminder_service_persists_and_schedules_reminder(tmp_path) -> None:
    clock = ManualClock()
    timers = FakeTimerFactory()
    service = ReminderService(
        tmp_path / "reminders.json",
        clock=clock,
        timer_factory=timers,
    )

    reminder = service.create_reminder(10, "Stretch.")

    payload = json.loads((tmp_path / "reminders.json").read_text(encoding="utf-8"))
    assert payload == [
        {
            "id": reminder.id,
            "text": "Stretch.",
            "due_at": "2026-09-23T18:40:00+00:00",
        }
    ]
    assert len(timers.timers) == 1
    assert timers.timers[0].delay_seconds == 600


def test_reminder_service_reloads_pending_reminders_and_schedules_due_time(
    tmp_path,
) -> None:
    clock = ManualClock()
    reminders_file = tmp_path / "reminders.json"
    reminders_file.write_text(
        json.dumps(
            [
                {
                    "id": "abc",
                    "text": "Check oven.",
                    "due_at": (clock.now + timedelta(minutes=5)).isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )
    timers = FakeTimerFactory()

    service = ReminderService(
        reminders_file,
        clock=clock,
        timer_factory=timers,
    )

    assert service.list_pending_reminders()[0].text == "Check oven."
    assert len(timers.timers) == 1
    assert timers.timers[0].delay_seconds == 300


def test_due_reminder_notifies_speaks_and_removes_pending_reminder(tmp_path) -> None:
    clock = ManualClock()
    timers = FakeTimerFactory()
    notifications: list[str] = []
    spoken: list[str] = []
    service = ReminderService(
        tmp_path / "reminders.json",
        clock=clock,
        timer_factory=timers,
        notifier=notifications.append,
        speaker=spoken.append,
    )

    service.create_reminder(1, "Stand up.")
    timers.timers[0].callback()

    assert notifications == ["Reminder: Stand up."]
    assert spoken == ["Reminder: Stand up."]
    assert service.format_pending_reminders() == "You have no pending reminders."


def test_notification_failure_does_not_prevent_spoken_reminder(tmp_path) -> None:
    timers = FakeTimerFactory()
    spoken: list[str] = []

    def failing_notifier(message: str) -> None:
        raise RuntimeError("notification unavailable")

    service = ReminderService(
        tmp_path / "reminders.json",
        timer_factory=timers,
        notifier=failing_notifier,
        speaker=spoken.append,
    )

    service.create_reminder(1, "Drink water.")
    timers.timers[0].callback()

    assert spoken == ["Reminder: Drink water."]


def test_list_reminders_is_ordered_and_hides_ids_and_paths(tmp_path) -> None:
    clock = ManualClock()
    timers = FakeTimerFactory()
    service = ReminderService(
        tmp_path / "reminders.json",
        clock=clock,
        timer_factory=timers,
    )

    service.create_reminder(20, "Later.")
    service.create_reminder(5, "Sooner.")

    assert service.format_pending_reminders() == (
        "Pending reminders: in 5 minutes, Sooner.; in 20 minutes, Later.."
    )
