"""Habit layer for the tools people actually rely on.

Pure functions live here so each category can be tested without the model,
the window, or a live account. The tools stay the source of truth. This
package decides what to show and what to call next.
"""

from arelis.core.reliance.capture import Capture, classify_capture
from arelis.core.reliance.conflicts import Overlap, find_overlaps, overlap_line
from arelis.core.reliance.last_object import StickyDesk, StickyRef
from arelis.core.reliance.leave_now import leave_line
from arelis.core.reliance.mail_reply import (
    SendReady,
    frequent_from_sent,
    rank_unread,
    send_ready,
)
from arelis.core.reliance.morning import MorningPlate, PlateRow, compose_morning, render_plate

__all__ = [
    "Capture",
    "MorningPlate",
    "Overlap",
    "PlateRow",
    "SendReady",
    "StickyDesk",
    "StickyRef",
    "classify_capture",
    "compose_morning",
    "find_overlaps",
    "frequent_from_sent",
    "leave_line",
    "overlap_line",
    "rank_unread",
    "render_plate",
    "send_ready",
]
