# Memory

Arelis saves durable facts about you and your work: things such as a preference,
a project you work on, or a detail you asked her to remember. Each fact keeps
the date it was first saved and the date it last changed. If she hears the
same fact again in slightly different words, she updates the existing fact
instead of adding a second copy.

"My finder is a 9x50 right-angle finder" and "Dana's finder is a 9x50 right
angle finder" count as one fact: the same words in the same order, with only
"my", your own name, small words like "a" or "the", and punctuation changed.
She recognises your own name from the `name` and `prefer_called` lines in
`data/profile.yaml`, so fill those in. Your name counts only at the start of a
fact or as "Dana's", so for someone called Will, "I will sell my scope" keeps
its "will". A changed number or value ("8x50" instead of "9x50", Jupiter
instead of Saturn), someone else's thing ("my sister's finder"), an added word
("least favourite", "ex-wife", "used to", "not", "cannot"), or the same words
in a new order ("Boston to Denver" and "Denver to Boston") keeps the facts
separate. A bigger rewording, such as "the finder on my telescope is a right
angle 9x50 finderscope", is saved as its own fact.

## See, edit, or forget what she remembers

Open **Settings → memory**. The list is the facts she uses as durable
knowledge.

- Each fact shows the date it was created and, if it changed later, the date
  it was updated.
- Select a fact and click **edit** to fix the wording. The original date stays;
  only the updated date changes.
- Select one or more facts and click **forget** to stop her using them. You can
  Shift-click or Ctrl-click to select more than one.
- By keyboard: press **Ctrl+,** to open Settings (it works from the chat
  window too). Tab twice to reach the Settings tabs, use the arrow keys to
  pick memory, then Tab twice to the list and use the arrow keys. Enter edits
  the selected fact and Delete forgets the selected facts. In the edit box, Tab
  moves to **Save** and **Cancel**. Screen reader names are in
  [Accessibility](accessibility.md).

You can also ask her in chat to remember or forget something. Those changes
still go through an Allow card, and then they appear in this same list.

Older facts that were waiting for a click under History are kept and shown
here, including ones that were worded almost the same as a fact she already
had. A leftover wording of something you already forgot or declined stays
forgotten.

## How she uses those facts in a chat

Each time you send a message, she pulls a small ranked set of memories that
are relevant to that ask: durable facts, plus any preferences or decisions
that also match. Unrelated memories stay out of the prompt, even if she has
many of them. The block is capped at 6 memories and 800 characters.

The full list still lives under Settings, memory. If she does not bring up
something you expected, check that list, or ask her to remember it.
