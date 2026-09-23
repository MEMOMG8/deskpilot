from deskpilot_backend.desktop_state import (
    DesktopStateController,
    WakeWordVisualController,
)


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


def test_wake_word_activation_enters_listening_then_returns_to_idle() -> None:
    controller = DesktopStateController()
    visible_states: list[str] = []
    scheduled_callbacks = []

    def schedule_hide(delay_ms, callback):
        scheduled_callbacks.append((delay_ms, callback))

    visual_controller = WakeWordVisualController(
        state=controller,
        show_border=lambda: visible_states.append("shown"),
        hide_border=lambda: visible_states.append("hidden"),
        schedule_hide=schedule_hide,
    )

    visual_controller.activate()

    assert controller.state == "listening"
    assert visible_states == ["shown"]
    assert scheduled_callbacks[0][0] == 4000

    scheduled_callbacks[0][1]()

    assert controller.state == "idle"
    assert visible_states == ["shown", "hidden"]
