"""The conversation archive: durable, searchable, and invisible to jobs."""

from __future__ import annotations

from pathlib import Path

from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore


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
    assert [m["role"] for m in prompt] == ["user", "assistant", "system"]
    assert prompt[1]["content"] == "Sent your text to wife."
    assert "send_sms" in prompt[2]["content"]
    assert "tools used this turn" not in prompt[1]["content"]
    spoken = memory.as_ollama(include_notes=False)
    assert [m["role"] for m in spoken] == ["user", "assistant"]
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


def test_cancelled_send_is_redacted_in_the_prompt() -> None:
    memory = SessionMemory()
    memory.add("user", "text 5555550123 and tell him hes a bitch")
    memory.mark_last_user_cancelled()
    memory.add("user", "what is 17 times 19?")
    prompt = " ".join(m["content"] for m in memory.as_ollama())
    assert "5555550123" not in prompt
    assert "bitch" not in prompt
    assert "Stopped a send" in prompt
    assert "17 times 19" in prompt


