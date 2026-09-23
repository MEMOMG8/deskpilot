import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_hex
from typing import Protocol

from deskpilot_backend.speech import SpeechEngineError, speak_text

DEFAULT_REMINDERS_FILE = Path.home() / "Documents" / "DeskPilot" / "reminders.json"
MAX_REMINDER_TEXT_LENGTH = 500
LOGGER = logging.getLogger(__name__)

Clock = Callable[[], datetime]
Notifier = Callable[[str], None]
Speaker = Callable[[str], None]


class TimerHandle(Protocol):
    def cancel(self) -> None:
        ...


TimerFactory = Callable[[float, Callable[[], None]], TimerHandle]


class ReminderStoreError(RuntimeError):
    """Raised when local DeskPilot reminders cannot be read or written safely."""


@dataclass(frozen=True)
class Reminder:
    id: str
    text: str
    due_at: datetime


class ReminderService:
    def __init__(
        self,
        reminders_file: Path = DEFAULT_REMINDERS_FILE,
        *,
        clock: Clock | None = None,
        timer_factory: TimerFactory | None = None,
        notifier: Notifier | None = None,
        speaker: Speaker | None = None,
    ) -> None:
        self.reminders_file = reminders_file
        self._clock = clock or _utc_now
        self._timer_factory = timer_factory or _threading_timer
        self._notifier = notifier or (lambda message: None)
        self._speaker = speaker or _speak_reminder
        self._lock = threading.RLock()
        self._timers: dict[str, TimerHandle] = {}
        self.reload_pending_reminders()

    def create_reminder(self, minutes: int, text: str) -> Reminder:
        due_at = self._now() + timedelta(minutes=minutes)
        reminder = Reminder(id=token_hex(8), text=text, due_at=due_at)

        with self._lock:
            reminders = self._load_reminders()
            reminders.append(reminder)
            reminders.sort(key=lambda item: item.due_at)
            self._save_reminders(reminders)
            self._schedule_locked(reminder)

        return reminder

    def list_pending_reminders(self) -> list[Reminder]:
        with self._lock:
            reminders = self._load_reminders()
            reminders.sort(key=lambda item: item.due_at)
            return reminders

    def format_pending_reminders(self) -> str:
        reminders = self.list_pending_reminders()
        if not reminders:
            return "You have no pending reminders."

        parts = [
            f"in {_format_minutes(_minutes_until(reminder.due_at, self._now()))}, "
            f"{reminder.text}"
            for reminder in reminders
        ]
        return f"Pending reminders: {'; '.join(parts)}."

    def reload_pending_reminders(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

            reminders = self._load_reminders()
            reminders.sort(key=lambda item: item.due_at)
            if reminders:
                self._save_reminders(reminders)
            for reminder in reminders:
                self._schedule_locked(reminder)

    def stop(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    def _schedule_locked(self, reminder: Reminder) -> None:
        delay_seconds = max(0.0, (reminder.due_at - self._now()).total_seconds())
        self._timers[reminder.id] = self._timer_factory(
            delay_seconds,
            lambda reminder_id=reminder.id: self._deliver_reminder(reminder_id),
        )

    def _deliver_reminder(self, reminder_id: str) -> None:
        with self._lock:
            reminders = self._load_reminders()
            reminder = next(
                (item for item in reminders if item.id == reminder_id),
                None,
            )
            if reminder is None:
                self._timers.pop(reminder_id, None)
                return

            remaining_reminders = [
                item for item in reminders if item.id != reminder_id
            ]
            self._save_reminders(remaining_reminders)
            self._timers.pop(reminder_id, None)

        message = f"Reminder: {reminder.text}"
        try:
            self._notifier(message)
        except Exception:
            LOGGER.exception("Reminder notification failed.")

        try:
            self._speaker(message)
        except Exception:
            LOGGER.exception("Reminder speech failed.")

    def _load_reminders(self) -> list[Reminder]:
        if not self.reminders_file.exists():
            return []

        try:
            raw_reminders = json.loads(self.reminders_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReminderStoreError("Local reminders are unavailable.") from error

        reminders = []
        for raw_reminder in raw_reminders:
            reminders.append(
                Reminder(
                    id=str(raw_reminder["id"]),
                    text=str(raw_reminder["text"]),
                    due_at=_parse_datetime(str(raw_reminder["due_at"])),
                )
            )
        return reminders

    def _save_reminders(self, reminders: list[Reminder]) -> None:
        self.reminders_file.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": reminder.id,
                "text": reminder.text,
                "due_at": reminder.due_at.isoformat(),
            }
            for reminder in reminders
        ]

        try:
            self.reminders_file.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            raise ReminderStoreError("Local reminders are unavailable.") from error

    def _now(self) -> datetime:
        return _ensure_aware(self._clock())


def _threading_timer(delay_seconds: float, callback: Callable[[], None]) -> TimerHandle:
    timer = threading.Timer(delay_seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


def _speak_reminder(message: str) -> None:
    try:
        speak_text(message)
    except SpeechEngineError as error:
        raise ReminderStoreError("Reminder speech is unavailable.") from error


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: str) -> datetime:
    return _ensure_aware(datetime.fromisoformat(value))


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value


def _minutes_until(due_at: datetime, now: datetime) -> int:
    seconds = max(0.0, (due_at - now).total_seconds())
    return max(1, int((seconds + 59) // 60))


def _format_minutes(minutes: int) -> str:
    if minutes == 1:
        return "1 minute"

    return f"{minutes} minutes"
