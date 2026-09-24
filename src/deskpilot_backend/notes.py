from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from time import time_ns

DEFAULT_NOTES_DIRECTORY = Path.home() / "Documents" / "DeskPilot" / "notes"
MAX_NOTE_TEXT_LENGTH = 1000
MAX_SPOKEN_NOTE_LENGTH = 500


class NoteStoreError(RuntimeError):
    """Raised when local DeskPilot notes cannot be read or written safely."""


@dataclass
class NoteStore:
    notes_directory: Path = DEFAULT_NOTES_DIRECTORY

    def create_note(self, text: str) -> Path:
        self.notes_directory.mkdir(parents=True, exist_ok=True)

        for _attempt in range(10):
            note_path = self.notes_directory / self._generate_filename()
            try:
                with note_path.open("x", encoding="utf-8") as note_file:
                    note_file.write(text)
                    note_file.write("\n")
                return note_path
            except FileExistsError:
                continue

        raise NoteStoreError("Could not create a unique note file.")

    def read_latest_note(self) -> str | None:
        latest_note = self._latest_note_path()
        if latest_note is None:
            return None

        return latest_note.read_text(encoding="utf-8").strip()

    def count_notes(self) -> int:
        if not self.notes_directory.exists():
            return 0

        return sum(1 for path in self.notes_directory.glob("*.txt") if path.is_file())

    def ensure_directory(self) -> Path:
        self.notes_directory.mkdir(parents=True, exist_ok=True)
        return self.notes_directory

    def _latest_note_path(self) -> Path | None:
        if not self.notes_directory.exists():
            return None

        note_paths = [
            path for path in self.notes_directory.glob("*.txt") if path.is_file()
        ]
        if not note_paths:
            return None

        return max(note_paths, key=lambda path: path.name)

    @staticmethod
    def _generate_filename() -> str:
        timestamp = time_ns()
        return f"note_{timestamp}_{token_hex(4)}.txt"


def format_latest_note(note_text: str | None) -> str:
    if note_text is None:
        return "You do not have any notes yet."

    note_text = note_text.strip()
    if len(note_text) > MAX_SPOKEN_NOTE_LENGTH:
        note_text = f"{note_text[:MAX_SPOKEN_NOTE_LENGTH].rstrip()}..."

    return f"Latest note: {note_text}"


def format_note_count(note_count: int) -> str:
    if note_count == 1:
        return "You have 1 note."

    return f"You have {note_count} notes."
