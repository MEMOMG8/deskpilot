import asyncio
import sys
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest

from deskpilot_backend.windows_media import (
    MediaControlError,
    WindowsMediaController,
    _request_windows_manager,
)


class Session:
    source_app_user_model_id = "Spotify.exe"

    def __init__(self, result=True):
        self.calls = []
        self.result = result
        self.position = timedelta()
        self.start = timedelta()
        self.seek_result = True
        self.controls = SimpleNamespace(is_previous_enabled=True, is_playback_position_enabled=True)

    async def try_play_async(self):
        self.calls.append("play")
        return self.result

    async def try_pause_async(self):
        self.calls.append("pause")
        return self.result

    async def try_skip_next_async(self):
        self.calls.append("next_track")
        return self.result

    async def try_skip_previous_async(self):
        self.calls.append("previous_track")
        return self.result

    def get_timeline_properties(self):
        return SimpleNamespace(position=self.position, start_time=self.start)

    def get_playback_info(self):
        return SimpleNamespace(controls=self.controls)

    async def try_change_playback_position_async(self, position):
        self.calls.append(("seek", position))
        if self.seek_result:
            self.position = timedelta(microseconds=position // 10)
        return self.seek_result


class Manager:
    def __init__(self, session):
        self.session = session

    def get_sessions(self):
        return [self.session] if self.session else []

    def get_current_session(self):
        return self.session


def controller_for(manager, **kwargs):
    async def factory():
        return manager
    return WindowsMediaController(manager_factory=factory, **kwargs)


@pytest.mark.parametrize("operation", ["play", "pause", "next_track", "previous_track"])
def test_controls_current_session_with_explicit_operations(operation):
    session = Session()
    controller_for(Manager(session)).control(operation)
    assert session.calls == [operation]


def test_repeated_pause_never_toggles_or_plays():
    session = Session()
    controller = controller_for(Manager(session))
    controller.control("pause")
    controller.control("pause")
    assert session.calls == ["pause", "pause"]


@pytest.mark.parametrize("identity", ["Spotify.exe", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"])
def test_previous_advanced_spotify_seeks_then_skips_exactly_one_track(identity):
    session = Session()
    session.source_app_user_model_id = identity
    session.position = timedelta(seconds=60)
    controller_for(Manager(session)).control("previous_track")
    assert session.calls == [("seek", 0), "previous_track"]


def test_previous_from_start_skips_once_without_seek_or_second_skip():
    session = Session()
    controller_for(Manager(session)).control("previous_track")
    assert session.calls == ["previous_track"]


def test_previous_uses_timeline_start_in_windows_ticks():
    session = Session()
    session.start = timedelta(seconds=10)
    session.position = timedelta(seconds=40)
    controller_for(Manager(session)).control("previous_track")
    assert session.calls == [("seek", 100000000), "previous_track"]


def test_previous_waits_for_seek_acknowledgement_before_skipping():
    session = Session()
    session.position = timedelta(seconds=30)
    samples = iter([30, 30, 0])
    session.get_timeline_properties = lambda: SimpleNamespace(
        position=timedelta(seconds=next(samples)), start_time=timedelta()
    )
    controller_for(Manager(session)).control("previous_track")
    assert session.calls == [("seek", 0), "previous_track"]


@pytest.mark.parametrize("failure", ["seek_rejected", "seek_disabled", "previous_disabled"])
def test_previous_does_not_claim_success_or_skip_after_preparation_failure(failure):
    session = Session()
    session.position = timedelta(seconds=30)
    session.seek_result = failure != "seek_rejected"
    session.controls.is_playback_position_enabled = failure != "seek_disabled"
    session.controls.is_previous_enabled = failure != "previous_disabled"
    with pytest.raises(MediaControlError, match="Spotify"):
        controller_for(Manager(session)).control("previous_track")
    assert "previous_track" not in session.calls


def test_previous_does_not_skip_when_seek_timeline_never_updates():
    session = Session()
    session.position = timedelta(seconds=30)

    async def unacknowledged_seek(position):
        session.calls.append(("seek", position))
        return True

    session.try_change_playback_position_async = unacknowledged_seek
    with pytest.raises(MediaControlError, match="did not confirm"):
        controller_for(Manager(session)).control("previous_track")
    assert session.calls == [("seek", 0)]


def test_previous_rejected_after_seek_is_not_retried():
    session = Session(result=False)
    session.position = timedelta(seconds=30)
    with pytest.raises(MediaControlError, match="could not complete"):
        controller_for(Manager(session)).control("previous_track")
    assert session.calls == [("seek", 0), "previous_track"]


def test_previous_in_other_players_keeps_native_behavior():
    session = Session()
    session.source_app_user_model_id = "browser.exe"
    session.position = timedelta(seconds=60)
    controller_for(Manager(session)).control("previous_track")
    assert session.calls == ["previous_track"]


@pytest.mark.parametrize("operation", ["play", "pause", "next_track", "previous_track"])
def test_absent_session_is_an_error(operation):
    with pytest.raises(MediaControlError, match="No active Windows media session"):
        controller_for(Manager(None)).control(operation)


@pytest.mark.parametrize("identity", ["Spotify.exe", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"])
def test_play_does_not_relaunch_registered_spotify(identity):
    session = Session()
    session.source_app_user_model_id = identity
    launches = []
    controller_for(Manager(session)).control("play", ensure_spotify_open=lambda: launches.append(True))
    assert launches == []
    assert session.calls == ["play"]


def test_play_launches_spotify_and_waits_for_new_session():
    session = Session()
    manager = Manager(None)
    polls = []

    def current():
        polls.append(True)
        return session if len(polls) > 1 else None

    manager.get_current_session = current
    launches = []
    controller_for(manager).control("play", ensure_spotify_open=lambda: launches.append(True))
    assert launches == [True]
    assert len(polls) == 2
    assert session.calls == ["play"]


def test_launch_without_session_still_reports_failure():
    with pytest.raises(MediaControlError, match="No active Windows media session"):
        controller_for(Manager(None), startup_wait_seconds=0).control(
            "play", ensure_spotify_open=lambda: None
        )


def test_controls_windows_current_session_even_when_another_player_is_present():
    spotify, browser = Session(), Session()
    browser.source_app_user_model_id = "browser.exe"
    manager = Manager(browser)
    manager.get_sessions = lambda: [spotify, browser]
    controller_for(manager).control("play", ensure_spotify_open=lambda: pytest.fail("already open"))
    assert spotify.calls == []
    assert browser.calls == ["play"]


def test_rejected_control_and_native_errors_are_not_success():
    with pytest.raises(MediaControlError, match="could not complete"):
        controller_for(Manager(Session(result=False))).control("pause")

    async def failing_factory():
        raise OSError("private native details")

    with pytest.raises(MediaControlError, match="unavailable"):
        WindowsMediaController(manager_factory=failing_factory).control("play")


def test_timeout_is_bounded():
    async def stuck_factory():
        await asyncio.sleep(60)

    with pytest.raises(MediaControlError, match="timed out"):
        WindowsMediaController(manager_factory=stuck_factory, timeout_seconds=0.01).control("pause")


def test_worker_supports_callers_already_running_asyncio():
    caller_thread = threading.get_ident()
    worker_threads = []

    async def factory():
        worker_threads.append(threading.get_ident())
        return Manager(Session())

    async def caller():
        WindowsMediaController(manager_factory=factory).control("pause")

    asyncio.run(caller())
    assert worker_threads[0] != caller_thread


def test_invalid_operation_never_requests_a_session():
    with pytest.raises(MediaControlError, match="Unsupported"):
        controller_for(Manager(None)).control("arbitrary")


def test_windows_imports_are_lazy_and_platform_error_is_controlled(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(MediaControlError, match="only supported on Windows"):
        asyncio.run(_request_windows_manager())


@pytest.mark.parametrize("module", [
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
])
def test_missing_windows_dependency_is_controlled(monkeypatch, module):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(MediaControlError, match="support is missing"):
        asyncio.run(_request_windows_manager())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows runtime dependencies")
def test_installed_windows_namespaces_include_session_collection_support():
    # Real imports catch missing optional WinRT namespace packages that fakes hide.
    import importlib

    for module in (
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.media.control",
    ):
        importlib.import_module(module)
