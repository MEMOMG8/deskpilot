"""Local Windows media sessions. No Spotify API, credentials or UI automation."""

import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Literal, Protocol

MediaOperation = Literal["play", "pause", "next_track", "previous_track"]
NO_SESSION_MESSAGE = (
    "No active Windows media session. Open a player and start a song once, then try again."
)


class MediaControlError(RuntimeError):
    """A local media request could not be completed."""


class MediaTimeline(Protocol):
    position: timedelta
    start_time: timedelta


class MediaPlaybackControls(Protocol):
    is_previous_enabled: bool
    is_playback_position_enabled: bool


class MediaPlaybackInfo(Protocol):
    controls: MediaPlaybackControls


class MediaSession(Protocol):
    source_app_user_model_id: str

    def try_play_async(self) -> Awaitable[bool]: ...
    def try_pause_async(self) -> Awaitable[bool]: ...
    def try_skip_next_async(self) -> Awaitable[bool]: ...
    def try_skip_previous_async(self) -> Awaitable[bool]: ...
    def try_change_playback_position_async(self, position: int) -> Awaitable[bool]: ...
    def get_timeline_properties(self) -> MediaTimeline: ...
    def get_playback_info(self) -> MediaPlaybackInfo: ...


class MediaSessionManager(Protocol):
    def get_current_session(self) -> MediaSession | None: ...
    def get_sessions(self) -> Sequence[MediaSession]: ...


class MediaController(Protocol):
    def control(
        self,
        operation: MediaOperation,
        *,
        ensure_spotify_open: Callable[[], None] | None = None,
    ) -> None: ...


async def _request_windows_manager() -> MediaSessionManager:
    if sys.platform != "win32":
        raise MediaControlError("Windows media controls are only supported on Windows.")

    # Import on the worker thread, never while importing the app or running fakes.
    try:
        import winrt.windows.foundation  # registers async operation support
        import winrt.windows.foundation.collections  # required by get_sessions()
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    except ImportError as error:
        raise MediaControlError(
            "Windows media support is missing. Reinstall DeskPilot with its Windows dependencies."
        ) from error

    return await GlobalSystemMediaTransportControlsSessionManager.request_async()


def _is_spotify_session(session: MediaSession) -> bool:
    identity = session.source_app_user_model_id.casefold()
    return identity == "spotify.exe" or identity.startswith("spotifyab.spotifymusic_")


class WindowsMediaController:
    def __init__(
        self,
        *,
        manager_factory: Callable[[], Awaitable[MediaSessionManager]] | None = None,
        startup_wait_seconds: float = 4.0,
        timeout_seconds: float = 8.0,
    ) -> None:
        self._manager_factory = manager_factory or _request_windows_manager
        self._startup_wait_seconds = startup_wait_seconds
        self._timeout_seconds = timeout_seconds

    def control(
        self,
        operation: MediaOperation,
        *,
        ensure_spotify_open: Callable[[], None] | None = None,
    ) -> None:
        if operation not in {"play", "pause", "next_track", "previous_track"}:
            raise MediaControlError("Unsupported Windows media operation.")
        # A private worker also works from Qt/COM STA and callers with an asyncio loop.
        # WinRT objects are created, used and released on that worker.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="DeskPilotMedia") as worker:
            worker.submit(self._run, operation, ensure_spotify_open).result()

    def _run(self, operation: MediaOperation, opener: Callable[[], None] | None) -> None:
        try:
            asyncio.run(asyncio.wait_for(self._perform(operation, opener), self._timeout_seconds))
        except MediaControlError:
            raise
        except TimeoutError as error:
            raise MediaControlError("Windows media control timed out. Try again.") from error
        except Exception as error:
            raise MediaControlError("Windows media control is unavailable. Try again.") from error

    async def _perform(
        self, operation: MediaOperation, opener: Callable[[], None] | None
    ) -> None:
        manager = await self._manager_factory()
        launched = False
        if opener is not None and not any(_is_spotify_session(s) for s in manager.get_sessions()):
            opener()
            launched = True

        session = manager.get_current_session()
        if session is None and launched:
            deadline = asyncio.get_running_loop().time() + self._startup_wait_seconds
            while session is None and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.2)
                session = manager.get_current_session()
        if session is None:
            raise MediaControlError(NO_SESSION_MESSAGE)

        if operation == "previous_track" and _is_spotify_session(session):
            await self._prepare_spotify_previous(session)

        methods = {
            "play": session.try_play_async,
            "pause": session.try_pause_async,
            "next_track": session.try_skip_next_async,
            "previous_track": session.try_skip_previous_async,
        }
        if not await methods[operation]():
            raise MediaControlError(
                "The active Windows player could not complete the media command."
            )

    async def _prepare_spotify_previous(self, session: MediaSession) -> None:
        # Spotify's Previous restarts an advanced track. Seek to its start first,
        # then send exactly ONE Previous, so a single voice command goes back one
        # track without blindly sending two skips or changing play/pause state.
        controls = session.get_playback_info().controls
        if not controls.is_previous_enabled:
            raise MediaControlError("Spotify cannot go to the previous track in this session.")
        timeline = session.get_timeline_properties()
        start = timeline.start_time
        if timeline.position - start <= timedelta(milliseconds=500):
            return
        if not controls.is_playback_position_enabled:
            raise MediaControlError("Spotify cannot go directly to the previous track in this session.")

        ticks = ((start.days * 86400 + start.seconds) * 1000000 + start.microseconds) * 10
        if not await session.try_change_playback_position_async(ticks):
            raise MediaControlError("Spotify could not prepare the previous track. Try again.")

        # A successful request may precede the timeline update. Wait for its
        # acknowledgement rather than skipping against a stale advanced position.
        deadline = asyncio.get_running_loop().time() + 1.5
        while session.get_timeline_properties().position - start > timedelta(milliseconds=500):
            if asyncio.get_running_loop().time() >= deadline:
                raise MediaControlError("Spotify did not confirm the track position. Try again.")
            await asyncio.sleep(0.05)
