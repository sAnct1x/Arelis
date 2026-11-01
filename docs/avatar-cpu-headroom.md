# Leave CPU headroom for the avatar

While she writes a reply, the model server can keep every CPU core busy. Her animation
then has to wait its turn, and she can stutter even though each frame takes only a few
milliseconds to draw.

## On by default

The setting **Leave CPU headroom for the avatar** is on unless you turn it off. To
turn it off, open Settings, then the window tab, and uncheck it.

The change takes effect the next time Arelis starts the model server. Quit Arelis
fully (not just to the tray) and start it again. If the model server was started some
other way and is already running, Arelis leaves it alone and this setting does nothing.

## What it does

- The model server uses two fewer CPU cores than this PC has (at least one).
- On Windows the model server runs at below normal priority, so the window and her
  animation get the CPU first.

With the setting off, Arelis starts the model server exactly as it always has.

## The trade-off

Replies may come out a little slower, because the model server has fewer cores and a
lower priority. If replies feel too slow, turn the setting off again.

In the settings file the key is `llamacpp.avatar_headroom` (`true` or `false`).
If the key is missing, the setting is on.
