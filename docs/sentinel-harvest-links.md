# Sentinel harvest links

Sentinel can read a public web page for you. Some links are held back.

## Links that run

- A plain link to any public site, with no `?` part, runs right away.
- Any link to a known research site runs right away, even with a `?` part.
  These are arXiv, Wikipedia, and the other sites in Sentinel's harvest list.

## Links that are held back

A link to any other site is held back when it carries extra data in the
address. That means a `?` part (for example `?q=...`), a `;` part, or a user
name before the site name. Sentinel does not open it.

This stops a link from carrying your data off this PC inside its address.

## What to do

If you trust the site, remove the `?` part and try again, or use a site from
the harvest list.
