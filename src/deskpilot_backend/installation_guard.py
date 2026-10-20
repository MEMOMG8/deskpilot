"""Keep the Windows installer from replacing a running packaged application."""

import sys
from contextlib import contextmanager

INSTALLATION_MUTEX = r"Local\DeskPilot.Desktop.Running"


class WindowsMutex:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def create(self, name):
        handle = self.kernel.CreateMutexW(None, False, name)
        if not handle:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return handle

    def close(self, handle):
        self.kernel.CloseHandle(handle)


@contextmanager
def desktop_installation_guard(backend=None):
    # This is a lifetime marker, not a single-instance lock. Every running
    # packaged instance holds a handle; the marker disappears after the last exits.
    if backend is None and sys.platform != "win32":
        yield
        return
    backend = backend or WindowsMutex()
    handle = backend.create(INSTALLATION_MUTEX)
    try:
        yield
    finally:
        backend.close(handle)
