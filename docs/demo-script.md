# DeskPilot 90-Second Demo Script

## Pre-Demo Setup

Install the project and start the native tray app:

```powershell
python -m pip install -e ".[dev]"
python -m deskpilot_backend.desktop
```

Optional custom alias setup:

1. Say or type `open deskpilot settings`.
2. In `~/Documents/DeskPilot/settings.json`, add:

```json
{
  "version": 1,
  "command_capture_duration_seconds": 4,
  "recording_start_cue_enabled": true,
  "wake_listening_on_startup": false,
  "custom_aliases": {
    "open my projects": "open github"
  }
}
```

3. Restart the tray app so the native shell reloads settings.

## 90-Second Walkthrough

1. Start with the tray app visible.
   - "DeskPilot is a local-first Windows voice assistant. It uses local wake-word detection, local transcription, deterministic command routing, and explicit allowlists."

2. Enable wake-word listening from the tray.
   - Choose `Start wake word listening`.
   - Say: "Hey Jarvis."
   - Point out the cyan listening border.

3. Open an allowlisted app.
   - Say: "open calculator."
   - Expected: the border turns amber while processing, Calculator opens, DeskPilot narrates the result, and the border briefly turns green.

4. Show a media command.
   - Say: "Hey Jarvis."
   - Say: "mute."
   - Expected: DeskPilot toggles mute through a fixed Windows media key. Mention that media commands affect the active Windows media session.

5. Save a local note.
   - Say: "Hey Jarvis."
   - Say: "take a note follow up on the DeskPilot demo."
   - Expected: DeskPilot saves a local text note under `~/Documents/DeskPilot/notes`.

6. Set a one-minute reminder.
   - Say: "Hey Jarvis."
   - Say: "remind me in one minute to stretch."
   - Expected: DeskPilot schedules the local reminder. When due, it shows a tray notification and says "Reminder: stretch."

7. Use the custom alias.
   - Say: "Hey Jarvis."
   - Say: "open my projects."
   - Expected: DeskPilot opens GitHub because the alias maps to the existing fixed command `open github`.

8. Show safety behavior.
   - Say: "Hey Jarvis."
   - Say an unsupported command, such as "open random program."
   - Expected: no action executes, the border briefly turns red, and DeskPilot says: "I didn't catch that. Say help for available commands."

## Close

End by opening the tray menu and choosing `Stop wake word listening` or `Quit DeskPilot`.
