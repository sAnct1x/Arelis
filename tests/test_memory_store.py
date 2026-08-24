"""The conversation archive: durable, searchable, and invisible to jobs."""

from __future__ import annotations

import ast
from pathlib import Path

from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore


def test_a_message_written_through_the_sink_can_be_read_back(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "I climb on weekends.")
    memory.add("assistant", "Noted.", note="[tools used this turn: none]")

    messages = store.get_messages(store.session_id or "")
    assert len(messages) == 2
    assert messages[0]["content"] == "I climb on weekends."
    assert messages[1]["note"].startswith("[tools used this turn:")
    sessions = store.list_sessions()
    assert sessions[0]["title"] == "I climb on weekends."
    store.close()


def test_chat_notice_survives_archive_and_is_hidden_from_the_model(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "text my wife: hi")
    memory.add("notice", "Text from Robin Hale: Bro that man is SSG")
    memory.add("assistant", "Sent your text to wife.", note="[tools used this turn: send_sms]")

    rows = store.get_messages(store.session_id or "")
    assert [r["role"] for r in rows] == ["user", "notice", "assistant"]
    assert "Bro that man is SSG" in rows[1]["content"]

    prompt = memory.as_ollama()
    assert [m["role"] for m in prompt] == ["user", "assistant"]
    assert "send_sms" in prompt[1]["content"]
    spoken = memory.as_ollama(include_notes=False)
    assert spoken[1]["content"] == "Sent your text to wife."

    sid = store.session_id or ""
    store.close()
    again = MemoryStore(tmp_path / "memory.db")
    again.open_session(sid)
    restored = SessionMemory()
    restored.hydrate(again.get_messages(sid))
    assert restored.messages[1].role == "notice"
    assert "Bro that man is SSG" in restored.messages[1].content
    again.close()


def test_drop_prompt_prefix_skips_notices() -> None:
    memory = SessionMemory()
    memory.add("user", "feature wish")
    memory.add("assistant", "visualization interface")
    memory.add("notice", "Text from Robin Hale: hi")
    memory.add("user", "how would we approach this")
    memory.drop_prompt_prefix(2)
    roles = [m.role for m in memory.messages]
    assert roles == ["notice", "user"]
    assert memory.messages[-1].content == "how would we approach this"
    assert "Robin" in memory.messages[0].content


def test_attachment_turn_does_not_title_from_boilerplate(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add(
        "user",
        "Attachments for this turn (call the listed tool; do not invent contents):\n"
        "- data/drops/x.png (image) → vision\n\n"
        "describe this image to me",
    )
    sessions = store.list_sessions()
    assert sessions[0]["title"] == "describe this image to me"
    store.close()


def test_summary_and_pending_facts_land_in_the_archive(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.set_summary("They discussed the interferometer.")
    memory.add_pending_fact("User builds an interferometer")

    assert store.get_summary(store.session_id or "") == "They discussed the interferometer."
    row = store._conn.execute(
        "SELECT text, source, status FROM facts WHERE status = 'pending'"
    ).fetchone()
    assert row is not None
    assert row["text"] == "User builds an interferometer"
    assert row["source"] == "proposed"
    store.close()


def test_search_finds_an_old_message_by_keyword(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "The telescope pointing model drifted again.")
    memory.add("assistant", "We should recalibrate the mounts.")

    hits = store.search("telescope")
    assert hits
    assert "telescope" in hits[0].content.lower()
    store.close()


def test_search_skips_inbound_sms_notices(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "what did we talk about")
    memory.add("notice", "Text from Robin Hale: Bro that man is SSG")
    memory.add("assistant", "We were talking about the visualization interface.")

    hits = store.search("Robin")
    assert hits == []
    hits = store.search("visualization")
    assert hits
    assert all(h.role != "notice" for h in hits)
    store.close()


def test_delete_session_cascades_messages(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    sid = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "delete me later")
    memory.set_summary("ephemeral")
    assert store.get_messages(sid)
    assert store.get_summary(sid) == "ephemeral"
    assert store.delete_session(sid) is True
    assert store.get_session(sid) is None
    assert store.get_messages(sid) == []
    assert store.get_summary(sid) == ""
    assert store.delete_session(sid) is False
    store.close()


def test_session_memory_without_a_sink_writes_nothing(tmp_path: Path) -> None:
    """The job runner's isolation guarantee: no sink means no archive traffic."""
    db = tmp_path / "memory.db"
    store = MemoryStore(db)
    store.close()

    memory = SessionMemory()
    memory.add("user", "this must not be archived")
    memory.set_summary("nor this")
    memory.add_pending_fact("nor this fact")

    # Re-open the same path; the schema exists but no rows were added by memory.
    reopened = MemoryStore(db)
    assert reopened.list_sessions() == []
    assert reopened.search("archived") == []
    reopened.close()


def test_the_job_runner_builds_session_memory_with_no_sink() -> None:
    """Scheduled runs must stay isolated by construction, not by remembering."""
    source = Path("arelis/jobs/runner.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "SessionMemory":
                calls.append(node)
            elif isinstance(func, ast.Attribute) and func.attr == "SessionMemory":
                calls.append(node)
    assert calls, "runner.py no longer constructs SessionMemory"
    for call in calls:
        for keyword in call.keywords:
            assert keyword.arg != "sink", "job runner must not attach a memory sink"
        assert call.args == [], "job runner must use the bare SessionMemory() default"


def test_glass_launch_starts_new_and_prunes_empty_shells(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    filled = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "last night")
    empty = store.start_session()
    assert store.latest_session_id(require_messages=False) == empty
    fresh = store.start_glass_session()
    assert fresh != filled
    assert fresh != empty
    assert store.get_session(empty) is None
    assert store.get_session(filled) is not None
    assert store.get_messages(filled)[0]["content"] == "last night"
    store.close()


def test_glass_launch_refuses_to_prune_a_shell_that_has_messages(
    tmp_path: Path, monkeypatch
) -> None:
    """The prune deletes by ordering, so it has to re-check emptiness.

    started_at is second-resolution and the leftover/filled lookups are two
    different queries, so two conversations opened in the same second can be
    ordered differently by each — at which point the newest-overall row is a
    thread with messages and deleting it cascades the messages with it. The
    disagreement is forced here rather than waited for.
    """
    store = MemoryStore(tmp_path / "memory.db")
    older = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "real thread")
    newer = store.start_session()
    memory.add("user", "also real")
    monkeypatch.setattr(
        store,
        "latest_session_id",
        lambda *, require_messages=True, room_id=None: newer if require_messages else older,
    )

    store.start_glass_session()

    assert store.get_session(older) is not None
    assert store.get_messages(older)[0]["content"] == "real thread"
    assert store.get_session(newer) is not None
    store.close()


def test_mint_session_does_not_change_the_open_seat(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    pc = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "desk talk")
    phone = store.mint_session()
    assert store.session_id == pc
    assert phone != pc
    assert store.append_to_session(phone, "user", "from the plane")
    assert store.session_id == pc
    assert [row["content"] for row in store.get_messages(pc)] == ["desk talk"]
    assert [row["content"] for row in store.get_messages(phone)] == ["from the plane"]
    store.close()


def test_a_conversation_remembers_which_room_it_belongs_to(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    general = store.start_session()
    in_room = store.start_session(room_id="physics")

    assert store.get_session(general)["room_id"] == ""
    assert store.get_session(in_room)["room_id"] == "physics"
    assert [s["id"] for s in store.list_sessions(room_id="physics")] == [in_room]
    assert [s["id"] for s in store.list_sessions(room_id="")] == [general]
    assert len(store.list_sessions()) == 2
    store.close()


def test_a_cold_launch_cannot_prune_a_rooms_empty_thread(tmp_path: Path) -> None:
    """A room's thread is durable by design, including before it has anything in it.

    Make a room, say nothing, close the app: the prune looks for the newest
    empty shell and that is exactly what a just-created room thread is. Deleting
    it would mean rooms silently lose their continuity whenever you open one and
    get distracted, which is most of the times you open one.
    """
    store = MemoryStore(tmp_path / "memory.db")
    memory = SessionMemory(sink=store)
    store.start_session()
    memory.add("user", "general talk")
    room_thread = store.start_session(room_id="physics")

    store.start_glass_session()

    assert store.get_session(room_thread) is not None
    store.close()


def test_cancelled_user_turn_is_omitted_from_the_prompt() -> None:
    """2.4: stop keeps the bubble, but the next turn must not continue that ask."""
    memory = SessionMemory()
    memory.add("user", "Write me five paragraphs about the history of optics")
    memory.mark_last_user_cancelled()
    memory.add("user", "what is an if else loop?")
    prompt = " ".join(m["content"] for m in memory.as_ollama())
    assert "five paragraphs" not in prompt
    assert "if else" in prompt
    assert memory.messages[0].content.startswith("Write me")
