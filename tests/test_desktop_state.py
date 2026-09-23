from deskpilot_backend.desktop_state import (
    DesktopStateController,
    NativeWakeWordCommandController,
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


def test_wake_word_activation_can_stay_visible_until_command_finishes() -> None:
    controller = DesktopStateController()
    visible_states: list[str] = []
    scheduled_callbacks = []

    visual_controller = WakeWordVisualController(
        state=controller,
        show_border=lambda: visible_states.append("shown"),
        hide_border=lambda: visible_states.append("hidden"),
        schedule_hide=lambda delay_ms, callback: scheduled_callbacks.append(
            (delay_ms, callback)
        ),
    )

    visual_controller.activate(auto_hide=False)

    assert controller.state == "listening"
    assert visible_states == ["shown"]
    assert scheduled_callbacks == []

    visual_controller.deactivate()

    assert controller.state == "idle"
    assert visible_states == ["shown", "hidden"]


def test_native_wake_word_command_resumes_when_still_enabled() -> None:
    controller = NativeWakeWordCommandController()

    controller.enable_wake_word()
    started = controller.begin_command_after_wake_word()
    should_resume = controller.finish_command()

    assert started is True
    assert should_resume is True
    assert controller.command_in_progress is False
    assert controller.wake_word_enabled is True


def test_native_wake_word_command_does_not_resume_when_disabled_mid_command() -> None:
    controller = NativeWakeWordCommandController()

    controller.enable_wake_word()
    started = controller.begin_command_after_wake_word()
    controller.disable_wake_word()
    should_resume = controller.finish_command()

    assert started is True
    assert should_resume is False
    assert controller.command_in_progress is False
    assert controller.wake_word_enabled is False


def test_native_wake_word_command_rejects_duplicate_processing() -> None:
    controller = NativeWakeWordCommandController()

    controller.enable_wake_word()

    assert controller.begin_command_after_wake_word() is True
    assert controller.begin_command_after_wake_word() is False
