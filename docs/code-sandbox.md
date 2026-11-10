# Running code: the sandbox

When you ask Arelis to work something out in Python (fit a curve, run an
analysis, make a plot), she can now write the code and run it herself, with
no Allow card, in a sandbox. If that code needs to change one of your files,
or to use the network, she asks you first.

A short numerics cell (`python`) is for math, a fit, or a chart saved in
the work folder. It cannot use the network or change a file you named. Those
programs run through `run_script` in the same sandbox, so the first attempt
is refused and the same code again shows the network or file card below.

## What the sandbox is

- **Its own folder.** The code runs in this chat turn's work folder
  (`outputs/work/<turn>/` in Arelis's data folder). It can create, change and
  delete files there freely. A chart it saves there as a PNG shows in chat.
- **Your files are read only.** It can read your data files, but writing,
  deleting, moving or renaming anything outside its folder is refused, and
  nothing is changed there.
- **No network unless you allow it.** A first run that tries to reach the
  internet or look up a host name is refused, and nothing is sent. When
  Arelis tries the same code again, you see a card that names the hosts it
  tried to reach, or says network access. If you allow it, that run may use
  the network. If you don't, nothing changes.
- **No other programs.** It cannot start another program or a shell.
- **Time and memory caps.** It stops after 60 seconds (she can ask for up to
  120). On Windows it also stops at 2 GB of memory or 130 seconds of CPU.

## When the code wants to change your files

The first run is refused at that write and nothing outside the folder
changes. When Arelis tries the same code again, you see a card titled **Let this code
change your files**. It lists each path and what the code wants to do to it
(write, delete or move), and shows the whole code. If you allow it, that run
may change exactly those paths. Network stays off unless the same card also
asked for it, and the caps stay on. If you don't, nothing changes.

Running a script that is already in one of your projects is unchanged: it
runs as you, with full access, after you allow it.

## What is enforced and what is best effort

Be clear on this: the sandbox stops mistakes and ordinary code. It is not a
security boundary against code written to escape it.

Enforced by Windows (a job object around the process):

- Only one process. Starting a second process fails.
- The 2 GB memory cap and the 130 second CPU cap.
- The process dies if Arelis stops waiting for it or closes.

Enforced by Arelis:

- The wall-clock limit. Arelis kills the process when time is up.
- The environment. The code gets no API keys, tokens or passwords from
  Arelis's environment.

Best effort (a Python audit hook inside the sandboxed process):

- The file guard, the network guard and the program guard. They catch
  everything that goes through Python itself, including numpy, pandas,
  matplotlib and astropy writes. A compiled library that writes files or
  opens connections on its own, or code that uses `ctypes`, is not seen.
  The same gap covers `os.open` / `os.rename` with an outside `dir_fd`, and
  `os.mkfifo`: those do not raise the audit events we catch.
- On macOS and Linux, starting another Python through multiprocessing
  spawn or forkserver is blocked by replacing `_posixsubprocess.fork_exec`
  before the script runs (that call raises no audit event). On Windows the
  job object already allows only one process, and `_winapi.CreateProcess`
  is audited.
- Proxy settings point at a closed local port, which also stops many
  compiled libraries that honour them.
- Connections to this computer (`localhost`) are allowed, because Python
  uses them internally. Listening on every interface (empty host,
  `0.0.0.0`, or `::`) is refused.

On macOS and Linux there is no job object: the memory cap is not applied,
the CPU cap uses the system limit, and the program guard is the audit hook
plus the `fork_exec` patch above.

## Not in this version yet

- Other languages (R, Julia, and so on).
- Editing code in your own projects through the sandbox.
