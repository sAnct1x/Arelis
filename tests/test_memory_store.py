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
