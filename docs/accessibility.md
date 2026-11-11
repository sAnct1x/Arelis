# Accessibility

Screen readers and Windows UI Automation can reach the message box in
the chat window, and the Allow and Deny buttons on a confirmation
card. The message box is named Message. The buttons are named Allow
and Deny; activating them allows or denies that step.

While the Overseer is open, the chat composer and transcript are hidden
and disabled, so a screen reader or UI Automation client sees them as
hidden or disabled and cannot send from them. When the Overseer closes,
chat comes back for the current theme: a reply that arrived while it was
open is visible, and in Filament the transcript stays on the chat tile.
