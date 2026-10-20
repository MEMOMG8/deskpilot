import pytest

from deskpilot_backend.installation_guard import INSTALLATION_MUTEX, desktop_installation_guard


class FakeMutex:
    def __init__(self):
        self.calls = []

    def create(self, name):
        self.calls.append(("create", name))
        return 123

    def close(self, handle):
        self.calls.append(("close", handle))


def test_installer_marker_is_held_for_application_lifetime():
    backend = FakeMutex()
    with desktop_installation_guard(backend):
        assert backend.calls == [("create", INSTALLATION_MUTEX)]
    assert backend.calls[-1] == ("close", 123)


def test_installer_marker_is_released_after_application_error():
    backend = FakeMutex()
    with pytest.raises(RuntimeError):
        with desktop_installation_guard(backend):
            raise RuntimeError("startup failed")
    assert backend.calls[-1] == ("close", 123)


def test_cannot_silently_run_without_installer_marker():
    class BrokenMutex(FakeMutex):
        def create(self, name):
            raise OSError("mutex unavailable")

    with pytest.raises(OSError):
        with desktop_installation_guard(BrokenMutex()):
            pytest.fail("Application must not start without its marker")
