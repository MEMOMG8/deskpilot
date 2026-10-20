import pytest


class FakeMediaController:
    def __init__(self):
        self.calls = []
        self.spotify_open = False
        self.error = None

    def control(self, operation, *, ensure_spotify_open=None):
        if ensure_spotify_open is not None and not self.spotify_open:
            ensure_spotify_open()
        if self.error is not None:
            raise self.error
        self.calls.append(operation)


@pytest.fixture
def media_controller():
    return FakeMediaController()
