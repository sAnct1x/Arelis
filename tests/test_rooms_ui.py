"""The banner that stops a room from being an invisible mode.

Entering a room changes which thread she is continuing, which folder she writes
to, and which model answers. None of that is visible in the transcript, so
without the strip the only symptom of being somewhere else is that she behaves
differently — which reads as her being unreliable rather than as you having
moved. The strip exists to make the mode legible, and the leave button exists so
there is a way out that does not require knowing a command.
"""

from __future__ import annotations

import asyncio

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType


def test_the_strip_is_absent_until_a_room_is_open(qt_app) -> None:
    from arelis.ui.panels.room import RoomStrip

    strip = RoomStrip()

    assert strip.isHidden()
    assert strip.room_id == ""


def test_the_strip_names_the_room_and_its_folder(qt_app) -> None:
    from arelis.ui.panels.room import RoomStrip

    strip = RoomStrip()
    strip.set_room(
        "physics", name="Physics", purpose="Analysing the survey data.", root="Lab Notes"
    )

    assert not strip.isHidden()
    assert strip.name.text() == "Physics"
    assert "Analysing the survey data." in strip.detail.text()
    assert "Lab Notes" in strip.detail.text()


def test_a_long_purpose_stays_one_line_and_keeps_the_rest_on_hover(qt_app) -> None:
    """Purpose is a paragraph by design — she reads all of it either way."""
    from arelis.ui.panels.room import RoomStrip

    purpose = "Analysing the survey data. " * 12
    strip = RoomStrip()
    strip.set_room("physics", name="Physics", purpose=purpose)
    strip.resize(360, 38)
    strip.show()
    qt_app.processEvents()

    assert "\n" not in strip.detail.text()
    assert strip.detail.toolTip() == purpose
    assert strip.leave_btn.geometry().right() <= strip.rect().right()
    assert strip.leave_btn.geometry().left() >= strip.world_btn.geometry().right()


def test_world_button_hides_when_the_stage_is_off(qt_app, monkeypatch) -> None:
    from arelis.ui.panels import room as room_mod
    from arelis.ui.panels.room import RoomStrip

    monkeypatch.setattr(room_mod, "world_stage_allowed", lambda: False)
    strip = RoomStrip()
    strip.set_room("physics", name="Physics")
    assert strip.world_btn.isHidden()


def test_leaving_puts_the_strip_away(qt_app) -> None:
    from arelis.ui.panels.room import RoomStrip

    strip = RoomStrip()
    strip.set_room("physics", name="Physics")

    strip.set_room("")

    assert strip.isHidden()
    assert strip.room_id == ""


def test_the_window_paints_the_room_it_is_told_about(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._on_event(
            Event(
                EventType.ROOM_CHANGED,
                {
                    "room_id": "physics",
                    "name": "Physics",
                    "purpose": "Analysing the survey data.",
                    "root": "Lab Notes",
                },
            )
        )

        assert window.conversation.room.room_id == "physics"
        assert window.conversation.room.name.text() == "Physics"
        assert not window.camera.track_btn.isHidden()
        assert not window.conversation.room.world_btn.isHidden()

        window._on_event(Event(EventType.ROOM_CHANGED, {"room_id": ""}))

        assert window.conversation.room.isHidden()
        assert window.camera.track_btn.isHidden()
        assert window.conversation.room.world_btn.isHidden()
        assert window.world_window.isHidden()
    finally:
        window.dispose()
        window.hide()
        window.loop.close()


def test_the_rooms_menu_lists_them_and_marks_the_open_one(tmp_path, qt_app) -> None:
    from arelis.rooms import RoomStore
    from arelis.ui.app import ArelisWindow, BusBridge

    store = RoomStore(tmp_path / "rooms.yaml")
    store.create("Physics")
    store.create("Writing")
    store.set_active("physics")
    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
            "_rooms": store,
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        menu = window._build_rooms_menu()
        labels = [act.text() for act in menu.actions() if not act.isSeparator()]
        assert labels[0] == "Physics"
        assert labels[1] == "Writing"
        assert labels[-1] == "leave"
        checked = [act.text() for act in menu.actions() if act.isChecked()]
        assert checked == ["Physics"]
        leave = menu.actions()[-1]
        assert leave.isEnabled()
    finally:
        window.dispose()
        window.hide()
        window.loop.close()


def test_the_rooms_menu_enter_is_the_same_as_typing(tmp_path, qt_app) -> None:
    from arelis.rooms import RoomStore
    from arelis.ui.app import ArelisWindow, BusBridge

    store = RoomStore(tmp_path / "rooms.yaml")
    store.create("Physics")
    bus = EventBus()
    loop = asyncio.new_event_loop()
    sent: list[str] = []

    async def capture(event: Event) -> None:
        sent.append(str(event.payload.get("text") or ""))

    bus.subscribe(EventType.USER_MESSAGE, capture)
    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
            "_rooms": store,
        },
        BusBridge(),
        loop,
        bus,
    )

    async def settle() -> None:
        await asyncio.sleep(0.05)
        await bus.drain()
        bus.stop()

    try:
        task = loop.create_task(bus.run())
        menu = window._build_rooms_menu()
        physics = next(act for act in menu.actions() if act.text() == "Physics")
        physics.trigger()
        loop.run_until_complete(settle())
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        assert sent == ["/room physics"]
    finally:
        window.dispose()
        window.hide()
        loop.close()


def test_the_leave_button_asks_for_the_same_thing_typing_does(qt_app) -> None:
    """One implementation of leaving, reached two ways.

    The window holds no reference to the orchestrator, so the button publishes
    the command rather than calling a method — the same route the composer and
    the history dock already take.
    """
    from arelis.ui.app import ArelisWindow, BusBridge

    bus = EventBus()
    loop = asyncio.new_event_loop()
    sent: list[str] = []

    async def capture(event: Event) -> None:
        sent.append(str(event.payload.get("text") or ""))

    bus.subscribe(EventType.USER_MESSAGE, capture)
    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        loop,
        bus,
    )
    async def settle(task) -> None:
        # The click schedules the publish onto this loop from outside it, so the
        # loop has to turn over before there is anything for drain() to wait on.
        await asyncio.sleep(0.05)
        await bus.drain()
        bus.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    try:
        task = loop.create_task(bus.run())
        window.conversation.room.set_room("physics", name="Physics")
        window.conversation.room.leave_btn.click()
        loop.run_until_complete(settle(task))

        assert sent == ["/leave"]
    finally:
        window.hide()
        loop.close()


def test_orbit_cannot_open_the_world(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._toggle_world(True)
        assert window.world_window.isHidden()
        window._on_event(
            Event(
                EventType.ROOM_CHANGED,
                {"room_id": "physics", "name": "Physics"},
            )
        )
        window._toggle_world(True)
        assert not window.world_window.isHidden()
        window._on_event(Event(EventType.ROOM_CHANGED, {"room_id": ""}))
        assert window.world_window.isHidden()
    finally:
        window.dispose()
        window.hide()
        window.loop.close()


def test_the_room_strip_is_not_on_the_atmosphere_tick(qt_app) -> None:
    """10 Hz on a smoked plate over the void is the ghost-orbit path."""
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window.conversation.room.set_room(
            "physics", name="Physics", purpose="Pose up."
        )
        window._toggle_world(True)
        from arelis.ui.glass import GlassFrame

        frames = window._atmosphere_glass_frames()
        assert window.conversation not in frames
        assert window.conversation.room not in frames
        assert window.conversation.drive not in frames
        for frame in window.world_window.findChildren(GlassFrame):
            assert frame not in frames
    finally:
        window.dispose()
        window.hide()
        window.loop.close()
