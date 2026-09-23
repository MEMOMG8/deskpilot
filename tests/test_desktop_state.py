from deskpilot_backend.desktop_state import DesktopStateController


def test_desktop_state_starts_idle() -> None:
    controller = DesktopStateController()

    assert controller.state == "idle"
    assert controller.is_listening is False


def test_show_listening_border_sets_listening_state() -> None:
    controller = DesktopStateController()

    state = controller.show_listening_border()

    assert state == "listening"
    assert controller.state == "listening"
    assert controller.is_listening is True


def test_hide_border_returns_to_idle_state() -> None:
    controller = DesktopStateController(state="listening")

    state = controller.hide_border()

    assert state == "idle"
    assert controller.state == "idle"
    assert controller.is_listening is False
