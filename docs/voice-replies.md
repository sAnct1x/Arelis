# Spoken replies

When you are talking with her, you can turn on a short first pass that
does not load her tools, so she can start speaking sooner. This is off
by default. Turn it on by setting `voice.lane.enabled: true` in
`config.local.yaml`.

With it on, if she needs to look something up, she says so (for
example, "Let me look that up.") and then uses her tools as usual. The
look-up line is only spoken; the written reply is the answer after the
tools have run. Typed chat is unchanged.

Switching between a spoken reply and a typed or tool turn may cost a
longer first wait, because the two paths use different prompts.

When she talks, each sentence is meant to be heard once.

If she pulls a reply back and puts another in its place, she does not
start that new reply from the first sentence when you already heard
that part. She continues from the first sentence you have not heard
yet.

A reply that is new from the start is still spoken in full.
