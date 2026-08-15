"""In-app notification center: pill + card + inbox. Not a dock."""

from arelis.notify.center import (
    CHANNELS,
    ChannelMode,
    Notice,
    NotificationCenter,
    calendar_lead_notices,
    channel_mode,
    load_channels,
    new_notice,
)

__all__ = [
    "CHANNELS",
    "ChannelMode",
    "Notice",
    "NotificationCenter",
    "calendar_lead_notices",
    "channel_mode",
    "load_channels",
    "new_notice",
]
