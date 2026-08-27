from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    """Every message that crosses the bus.

    Two of these carry a contract the UI depends on. ASSISTANT_DONE and ERROR
    are terminal: exactly one of them ends a turn, and the desktop composer
    stays disabled until it sees one. TOOL_CONFIRM and TOOL_CONFIRM_REPLY are a
    matched pair correlated by the "id" field, and a reply with an unknown id is
    dropped rather than applied to whatever confirm happens to be open.

    The one exception to ERROR being terminal is marked in the payload. An
    ERROR carrying scope "voice" reports a failure of the voice pipeline, which
    runs outside any turn: the microphone can fail while a typed turn is
    mid-flight, and treating that as the turn's ending would re-enable the
    composer and dismiss a confirm card the turn is still parked on.

    ASSISTANT_RETRACT withdraws everything published by ASSISTANT_DELTA since
    the last ASSISTANT_DONE. It exists because answer text is streamed before
    the loop knows whether the round is an answer at all: a round that ends in a
    tool call was a preamble, not a reply, and has to come back off the screen.

    PHYSICS_VERB is a closed lexicon hit in the physics room (heavier,
    freeze, undo). It mutates the live scene this frame and never starts
    a turn. The 9B is not on this path.

    CONVERSATION_END hangs up hands-free talk (goodbye / that's all / stop
    listening). The glass unlatches the two-arcs toggle the same way the
    chord does. It never starts a turn. The room you were in stays put.

    The voice events are a chain, not a group. VOICE_TRANSCRIPT enters the
    pipeline and the orchestrator turns it into a USER_MESSAGE. While an answer
    is streaming, ASSISTANT_DELTA also feeds the voice service: completed
    sentences become VOICE_AUDIO_READY before the turn ends. ASSISTANT_RETRACT
    cancels that in-flight speech when the painted text was only a tool
    preamble. VOICE_SPEAK is still the terminal hand-off — it flushes any
    remainder from the final written answer (and is the whole path for
    non-stream producers such as SMS cues). VOICE_AUDIO_READY carries one
    synthesized clip and is the only one the UI plays, because audio devices
    belong to the Qt thread and the bus is the way back to it.

    VOICE_SPEECH_DONE closes that chain and is terminal for one spoken reply,
    the way ASSISTANT_DONE is terminal for one turn. Exactly one is published
    per VOICE_SPEAK that gets past the speak_enabled gate, including when
    synthesis fails or the answer reduces to nothing speakable; a retract of an
    already-opened streamed utterance also publishes one so the microphone is
    not left waiting. Conversation mode cannot reopen the microphone without
    it: clips arrive one sentence at a time, so an empty player queue means
    "the next clip is not rendered yet" far more often than it means "she has
    finished talking".

    SESSION_LOAD and SESSION_LOADED are how the desktop switches conversations.
    The window holds no reference to the orchestrator or memory, so a click in
    the history dock cannot call a method on either: it publishes SESSION_LOAD,
    the orchestrator hydrates SessionMemory from the archive, and SESSION_LOADED
    carries the messages back for the chat to paint. A load while a turn is
    mid-flight is refused rather than raced.

    SMS_RECEIVED is inbound text while the desktop UI is open. The inbound
    watcher polls SMSGate Local Server GET /inbox and publishes one event per
    new message id. The UI always records it (Notifications unread + inbound_sms
    buffer). Chat/voice announcement waits while a turn owns the floor (model,
    Allow, send, spoken reply), then flushes as one batched system note — not
    into an agent turn, and not into the outbound draft.

    ROOM_CHANGED announces that the open room changed, which is a bigger event
    than it sounds: the conversation thread, the active project and the model
    role all moved at once. It is published after the swap has happened, and it
    carries the whole new state rather than a delta, so a surface that missed an
    earlier one still paints the truth. An empty room id means the general
    conversation. SESSION_LOADED still carries the messages — this event says
    which room they belong to.

    CALENDAR_CHANGED fires after a Google/Outlook write or a cache sync, from
    the operator's calendar tile or from the agenda tool. The tile reloads; it
    is not a turn event. TASKS_CHANGED is the same idea for local chores in
    memory.db. JOBS_CHANGED is for Windows scheduled jobs in jobs.yaml.

    FILE_READY is a document (or other openable file) that just landed on disk.
    The chat paints a card with Open / Show in folder. It does not auto-open.

    MOBILE_SYNC copies pocket talk into the conversation the phone was already
    in. It is not a turn: the phone already answered. Ingest opens that session
    first (or starts a new one when the phone had no thread). The orchestrator
    appends the lines; the glass paints them. No tools run, and no disclaimer.
    """

    USER_MESSAGE = "user_message"
    ASSISTANT_DELTA = "assistant_delta"
    ASSISTANT_RETRACT = "assistant_retract"
    ASSISTANT_DONE = "assistant_done"
    THINKING = "thinking"
    STATUS = "status"
    MODEL_SWITCH = "model_switch"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_CONFIRM = "tool_confirm"
    TOOL_CONFIRM_REPLY = "tool_confirm_reply"
    TURN_CANCEL = "turn_cancel"
    TURN_PAUSE = "turn_pause"
    TURN_RESUME = "turn_resume"
    ERROR = "error"
    VOICE_TRANSCRIPT = "voice_transcript"
    PHYSICS_VERB = "physics_verb"
    CONVERSATION_END = "conversation_end"
    VOICE_SPEAK = "voice_speak"
    VOICE_AUDIO_READY = "voice_audio_ready"
    VOICE_SPEECH_DONE = "voice_speech_done"
    IMAGE_READY = "image_ready"
    FILE_READY = "file_ready"
    MOBILE_SYNC = "mobile_sync"
    SESSION_LOAD = "session_load"
    SESSION_LOADED = "session_loaded"
    SMS_RECEIVED = "sms_received"
    ROOM_CHANGED = "room_changed"
    CALENDAR_CHANGED = "calendar_changed"
    TASKS_CHANGED = "tasks_changed"
    JOBS_CHANGED = "jobs_changed"


@dataclass(slots=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
