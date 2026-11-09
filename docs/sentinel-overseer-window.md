# The Overseer and the main window

The Overseer (the 3D Sentinel view) now draws in its own window surface,
on its own render thread. Before, it drew on the same thread as the main
Arelis window, and each Overseer frame waited for the graphics card before
the main window could draw. While the Overseer was open, her figure and the
chat could stutter, most of all while the model was answering, and opening
the Overseer could freeze the app for about a second.

What you should see:

- The main window stays as smooth with the Overseer open as with it closed.
- Opening the Overseer no longer freezes the main window. The Overseer
  itself may still take a moment to show its first frame.
- The close button (x) and Esc still close the Overseer.

If the Overseer stays empty, check the log for a line that starts with
"Sentinels window: scene graph error". It means the graphics driver could
not start a 3D surface for it.
