"""Knuckle curl in 3D, then a verb.

Each unused finger is a bone chain (MCP–PIP–DIP–tip). Curl is
1 - chord/chain. A fist aimed at the C920 still folds; tip–MCP
distance does not — that looks like an open finger pointing at you.

Closed aperture + high curl = fist = grab. Closed + straight fingers
= pinch. Stretch is two pinches held, not one hand, not pinch-release.

A still wrist that "opens" is a camera lie (horizontal fist twist).
A moving wrist that opens is a throw. Leave-fist uses that split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from arelis.spatial.types import Hand, HandsFrame

TrackState = Literal["idle", "fist", "pinch", "lost"]
GestureState = Literal["idle", "fist", "pinch", "both", "lost"]
PoseReading = Literal["open", "fist", "pinch", "ambiguous"]

# Image units. A hand stays nearer its last wrist than the other hand does.
LOCK_WRIST = 0.22
# Idle tracks follow this far, not LOCK_WRIST. 0.22 stole the catching
# fist after a drop: both wrists sit on the same disc (~0.16 apart).
IDLE_WRIST = 0.08
# Two MediaPipe hands this close are the same body (Left+Right of one fist).
# Real two-hand stretch has wrists farther than one palm.
TWIN_WRIST = 0.05
# Locked hand missing this many frames → give up; do not gift the close.
LOCK_MISS = 12


def _xy_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def follow_hand(
    hands: tuple[Hand, ...],
    *,
    label: str = "",
    wrist: tuple[float, float] | None = None,
    idle: bool = False,
) -> Hand | None:
    """Same physical hand. Never the tighter other close."""
    if not hands:
        return None
    # An idle track after a drop must not absorb the other fist on this
    # disc. Prefer the label we already owned; do not wrist-snap 0.22.
    if idle and label:
        named = [hand for hand in hands if hand.label == label]
        if not named:
            return None
        if len(named) == 1:
            cand = named[0]
        elif wrist is not None:
            cand = min(named, key=lambda hand: _xy_dist(hand.xy(0), wrist))
        else:
            cand = min(named, key=lambda hand: hand.pinch_metric())
        if wrist is not None and _xy_dist(cand.xy(0), wrist) > LOCK_WRIST:
            return None
        return cand
    # Wrist first while closed. MediaPipe Left/Right flips mid-stretch;
    # following the label then makes the two tracks swap bodies.
    if wrist is not None:
        nearest = min(hands, key=lambda hand: _xy_dist(hand.xy(0), wrist))
        limit = IDLE_WRIST if idle else LOCK_WRIST
        if _xy_dist(nearest.xy(0), wrist) <= limit:
            return nearest
        return None
    if label:
        named = [hand for hand in hands if hand.label == label]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            return min(named, key=lambda hand: hand.pinch_metric())
    return min(hands, key=lambda hand: hand.pinch_metric())


@dataclass(frozen=True)
class GestureParams:
    # Closed enough to enter. 0.45 sat on the lip of a careful pinch.
    aperture_on: float = 0.50
    # Open enough to leave. Release still has to beat a flick.
    aperture_off: float = 0.64
    # Straight fingers (low curl) + closed aperture = pinch.
    pinch_max_curl: float = 0.28
    frames_on: int = 2
    frames_off: int = 3
    # A still twist spikes aperture for ~300 ms. Don't unlatch the fist.
    # A sling moves the wrist; that path keeps frames_off.
    fist_off: int = 8
    # Same C920 lie as the fist. Pinch used to leave in frames_off=3.
    pinch_off: int = 8
    still_wrist: float = 0.035


def read_pose(hand: Hand, params: GestureParams | None = None) -> PoseReading:
    """Stateless reading. The FSM adds hysteresis and kind-lock."""
    p = params or GestureParams()
    aperture = hand.pinch_metric()
    curl = hand.hand_curl()
    if aperture >= p.aperture_on:
        return "open"
    if curl <= p.pinch_max_curl:
        return "pinch"
    return "fist"


@dataclass
class HandTrack:
    """One mind, one hand. The other track is someone else's."""

    params: GestureParams = field(default_factory=GestureParams)
    state: TrackState = "idle"
    hand: Hand | None = None
    locked_label: str = ""
    _held: int = 0
    _open: int = 0
    _miss: int = 0
    _want: str = ""
    _lock_wrist: tuple[float, float] | None = None

    @property
    def who(self) -> str:
        if self.locked_label:
            return self.locked_label
        if self.hand is not None:
            return self.hand.label
        return ""

    def wrist_xy(self) -> tuple[float, float] | None:
        if self.hand is not None:
            return self.hand.xy(0)
        return self._lock_wrist

    @property
    def coasting(self) -> bool:
        """Last closed pose, MediaPipe blinked. Overlay keeps this hand."""
        return (
            self._miss > 0
            and self.state in ("fist", "pinch")
            and self.hand is not None
        )

    def reset(self) -> None:
        self.state = "idle"
        self.hand = None
        self.locked_label = ""
        self._held = 0
        self._open = 0
        self._miss = 0
        self._want = ""
        self._lock_wrist = None

    def _remember(self, hand: Hand) -> None:
        self.hand = hand
        self._lock_wrist = hand.xy(0)
        if hand.label:
            self.locked_label = hand.label
        self._miss = 0

    def _unlock(self) -> None:
        self.hand = None
        self.locked_label = ""
        self._lock_wrist = None
        self._miss = 0

    def force_lost(self) -> None:
        if self.state != "idle":
            self.state = "lost"
        self._held = 0
        self._open = 0
        self._want = ""
        self._unlock()

    def observe(self, hand: Hand | None) -> TrackState:
        if hand is None:
            if self.state in ("fist", "pinch") and self.hand is not None:
                # Side-on fist: MediaPipe often returns no hands for a frame.
                # Clearing the track is the blink. Keep the last closed pose.
                self._miss += 1
                if self._miss >= LOCK_MISS:
                    self.state = "lost"
                    self._held = 0
                    self._open = 0
                    self._want = ""
                    self._unlock()
                return self.state
            if self.state != "idle":
                self.state = "lost"
            self._held = 0
            self._open = 0
            self._want = ""
            self.hand = None
            if self.locked_label or self._lock_wrist:
                self._miss += 1
                if self._miss >= LOCK_MISS:
                    self._unlock()
                    self.state = "idle"
            else:
                self._unlock()
            return self.state

        was_coasting = self._miss > 0 and self.state in ("fist", "pinch")
        locked = bool(self.locked_label or self._lock_wrist)
        p = self.params
        prev_wrist = self._lock_wrist
        if hand.clips_frame():
            # Pointer may still follow. Do not read aperture — clipped
            # tips invent an open hand and drop a live fist/pinch.
            self._remember(hand)
            if self.state in ("fist", "pinch"):
                if self._open:
                    self._open -= 1
                return self.state
            self._held = 0
            self._want = ""
            return self.state
        moving = (
            prev_wrist is not None
            and _xy_dist(hand.xy(0), prev_wrist) >= p.still_wrist
        )
        self._remember(hand)
        reading = read_pose(hand, p)
        if self.state == "lost" and locked and not was_coasting:
            # A sling often drops the hand for a few frames. Coming back
            # half-open used to snap closed and eat the throw.
            self.state = "idle"
            self._held = 0
            self._open = 0
            self._want = ""
        if self.state in ("idle", "lost"):
            if reading in ("fist", "pinch"):
                if self._want != reading:
                    self._want = reading
                    self._held = 1
                else:
                    self._held += 1
            else:
                self._held = 0
                self._want = ""
            if self._want and self._held >= p.frames_on:
                self.state = self._want  # type: ignore[assignment]
                self._held = 0
                self._open = 0
            elif self.state == "lost" and reading == "open":
                self.state = "idle"
        elif self.state in ("fist", "pinch"):
            # Kind is locked. A still twist spikes aperture; that is not
            # an open hand. A sling moves the wrist — honor that sooner.
            if hand.pinch_metric() > p.aperture_off:
                self._open += 1
            elif self._open:
                self._open -= 1
            hold = p.fist_off if self.state == "fist" else p.pinch_off
            need = hold if not moving else p.frames_off
            if self._open >= need:
                self.state = "idle"
                self._open = 0
                self._want = ""
        return self.state


@dataclass
class GestureMachine:
    params: GestureParams = GestureParams()
    tracks: list[HandTrack] = field(default_factory=list)
    _bare: GestureState = "idle"

    @property
    def state(self) -> GestureState:
        kinds = {track.state for track in self.tracks}
        has_fist = "fist" in kinds
        has_pinch = "pinch" in kinds
        if has_fist and has_pinch:
            return "both"
        if has_fist:
            return "fist"
        if has_pinch:
            return "pinch"
        if any(track.state == "lost" for track in self.tracks):
            return "lost"
        if not self.tracks:
            return self._bare
        return "idle"

    @property
    def hand(self) -> Hand | None:
        for track in self.tracks:
            if track.state == "fist" and track.hand is not None:
                return track.hand
        for track in self.tracks:
            if track.state == "pinch" and track.hand is not None:
                return track.hand
        for track in self.tracks:
            if track.hand is not None:
                return track.hand
        return None

    @property
    def locked_label(self) -> str:
        for track in self.tracks:
            if track.state in ("fist", "pinch") and track.who:
                return track.who
        return ""

    def reset(self) -> None:
        self.tracks.clear()
        self._bare = "idle"

    def step(self, frame: HandsFrame | None) -> GestureState:
        if frame is None:
            if self.state != "idle":
                self._bare = "lost"
            for track in self.tracks:
                track.force_lost()
            self.tracks.clear()
            return self.state

        leftover = list(frame.hands)
        if not leftover and not self.tracks:
            return self.state

        self._bare = "idle"
        closed = [t for t in self.tracks if t.state in ("fist", "pinch")]
        rest = [t for t in self.tracks if t.state not in ("fist", "pinch")]
        for track in closed + rest:
            found = follow_hand(
                tuple(leftover),
                label=track.who,
                wrist=track._lock_wrist,
                idle=track.state not in ("fist", "pinch"),
            )
            if found is not None:
                leftover = [hand for hand in leftover if hand is not found]
                track.observe(found)
            else:
                track.observe(None)
        for hand in leftover:
            if len(self.tracks) >= 2:
                break
            if self._wrist_taken(hand.xy(0)):
                continue
            track = HandTrack(params=self.params)
            track.observe(hand)
            self.tracks.append(track)
        self._collapse_twins()
        self.tracks = [
            track
            for track in self.tracks
            if track.hand is not None or track.state != "idle"
        ]
        return self.state

    def _wrist_taken(self, wrist: tuple[float, float]) -> bool:
        for track in self.tracks:
            other = track.wrist_xy()
            if other is not None and _xy_dist(wrist, other) <= TWIN_WRIST:
                return True
        return False

    def _collapse_twins(self) -> None:
        """One body, one track. A duplicate Left/Right must not look like two pinches."""
        kept: list[HandTrack] = []
        for track in self.tracks:
            wrist = track.wrist_xy()
            if wrist is None:
                kept.append(track)
                continue
            twin_at = None
            for i, other in enumerate(kept):
                other_w = other.wrist_xy()
                if other_w is not None and _xy_dist(wrist, other_w) <= TWIN_WRIST:
                    twin_at = i
                    break
            if twin_at is None:
                kept.append(track)
                continue
            other = kept[twin_at]
            if track.state in ("fist", "pinch") and other.state not in (
                "fist",
                "pinch",
            ):
                kept[twin_at] = track
        self.tracks = kept


def best_pinch(hands: tuple[Hand, ...]) -> float | None:
    if not hands:
        return None
    return min(hand.pinch_metric() for hand in hands)
