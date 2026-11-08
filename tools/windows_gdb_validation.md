# Sacrificial hosted Windows GDB validation (opt-in; review required)

This is **preparation**, not verified Windows capture support, not a fix, and not
wired to CI or HUD children. Requires existing runner GDB17.1 and existing Qt/test
packages. Never install/fetch symbols or run on Atria/local Windows. The sole
privilege permission is the standard debugger OWN-token SeDebugPrivilege attempt
on the temporary hosted Windows runner (decision250).

Proposed placement **after existing Windows Python/dependency setup**, separately
from all unchanged pytest/coverage commands, on the exact reviewed source head.
No workflow step is added here; reviewer must approve publication/placement.
Proposed single PowerShell command (do not execute until separately coordinated):

```powershell
# EXACT existing tests/conftest.py14,20 setup; step-local, NOT a backend workaround.
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QUICK_BACKEND = "rhi"
python tools/windows_gdb_validation.py --hosted-windows-proof
exit $LASTEXITCODE
```

Only stdout's sanitized JSON may be retained. No raw debugger transcript. GDB
stderr and child Qt stderr are discarded; MI stream messages stay transient in
bounded pipes. Unknown symbols become `unresolved`; only exact allowlisted Qt
function names/module basenames survive. No arguments, locals, source paths,
raw addresses, raw handles or memory. GUI/render native thread IDs transit only
private child IPC to match debugger threads; they are not persisted. This does
not try to obtain a QPA handle, call winId/create, or change any backend/env.

The harness fails closed unless the inherited QPA/Quick values match the existing
conftest defaults exactly; it never changes them itself.
The sacrificial scene is an ordinary animated QtQuick window using inherited
setup; it is NOT a backend workaround or the actual failing HUD. Lack of a
separate working render thread or useful Qt symbols is a FAILED availability
proof. GDB frame argument values/entry values are disabled; no locals/arguments request
is sent. Autoload/debuginfod are explicitly disabled and acknowledged before
attach. Version17.1 must be observed in bounded MI output before attach.

Bounds: max16 enumerated threads,12 frames per selected GUI/render thread,
256KiB total per private output pipe,8KiB line limit,512 queued lines. Only the
2 identified owned threads are unwound. Collection uses one aggregate24s monotonic
deadline (not per-command waits), then at most two2s detach attempts and1s waits
for each owned process. Child self-exit fallback28s. These are application-level
bounds, **not a statically proven hard OS wall-clock guarantee**: process creation,
small pipe writes, scheduler/kernel kill or a broken Windows debugger can stall.
The mocked tests prove checks, not host responsiveness. Do NOT add this capture
to the real60s children before actual bounded Windows validation. No original
60/120/180s deadline is modified. Any failed path stays nonzero, regardless of
whether fallback cleanup later detaches successfully.

Success requires useful Qt symbols for BOTH identified threads, explicit MI
detach acknowledgement, subsequent empty debugger thread list, then a post-detach
stdin roundtrip acknowledged by BOTH render and GUI callbacks, and normal child
exit0. Pre-detach queued progress alone cannot pass. GDB empty-thread state is a
debugger observation, not an independent OS debug-owner API measurement. Actual
Windows detach safety, native unwind usefulness and deadline margin remain
unvalidated; no handle-probe is used to pretend otherwise. On cleanup failure,
only these owned sacrificial processes are terminated and proof remains FAILED.

Local tests mock ALL debugger/process operations, including error/retained-thread/
resume/abnormal-exit paths. They must never be cited as actual Windows/GIL/native
proof. No production/HUD behavior, assertion, test backend, or required infra is
changed. Source1ee984/47diagnostics and parent identities remain intact.

Cleanup ownership is registered before debugger spawn: the caller retains its
Debugger object before `start()` can create GDB or initialize the bounded reader.
Debugger and child cleanup are independent even on kill/wait/reader exceptions.
Only fixed `exited`/`unconfirmed`/`not_started` outcomes are emitted; exceptions
are never printed. A wait failure is unconfirmed, never cleanup success. An
unconfirmed owned exit or forced child termination keeps proof FAILED.
