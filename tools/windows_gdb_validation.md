# Sacrificial hosted Windows GDB validation (opt-in; review required)

This is **preparation**, not verified Windows capture support, not a fix, and not
enabled by default or wired to HUD children. Requires existing runner GDB17.1 and existing Qt/test
packages. Never install/fetch symbols or run on Atria/local Windows. The sole
privilege permission is the standard debugger OWN-token SeDebugPrivilege attempt
on the temporary hosted Windows runner (decision250).

Proposed placement **after existing Windows Python/dependency setup**, separately
from all unchanged pytest/coverage commands, on the exact reviewed source head.
The temporary reviewed workflow opts in ONLY on `push` to the existing publication
branch `refs/heads/sentinel/pr6-overseer`, Windows, non-doc tier, not-cancelled.
This branch is recorded in archived actual PR544 metadata (47-followup-1705 /
live-pr.json.txt), not guessed from this local worktree. No repo variable/settings
or dispatch required/created. Remove this temporary proof after selected runtime
review. It is last in the existing test job after all original tests and dependencies.
Publication/execution still require coordinated review/app checks.
Proposed single PowerShell command (do not execute until separately coordinated):

```powershell
# EXACT existing tests/conftest.py14,20 setup; step-local, NOT a backend workaround.
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QUICK_BACKEND = "rhi"
python -m tools.windows_gdb_outer
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

The new standard Windows Job Object outer supervisor owns a private kill-on-close
job across ROOT EXIT. It reuses the existing child_proc native DLL/limit-structure
and venv-base-interpreter helpers; it does NOT change the product cell's caps or
call its active-process-limit1 spawn path. A private stdin gate prevents the new
root from starting any GDB/Qt descendants until assignment succeeds. Descendants
inherit the diagnostic job; no breakaway flags, process enumeration, PID/name
killing, global policy, native handle output, installs or debugger implementation.
Native job support is documented in Microsoft Learn Job Objects / QueryInformationJobObject.
If creation/config/assignment is unavailable, fail before gate release and kill
ONLY the unassigned waiting root. No permissive fallback.

Outer root wait35s; cleanup always terminates the OWNED JOB, including when root
already exited with inner cleanup-unconfirmed, then checks ActiveProcesses==0
for up to2s. Only this boolean survives; job accounting fields/handles are NEVER
printed. Remaining members invalidate even a rootexit0. CloseHandle kill-on-close
is independent final cleanup after terminate/query failure. The existing1minute
step ceiling remains unchanged. Parent-root liveness is NOT the ownership token.
Stderr DEVNULL, approved inner sanitized stdout inherited; fixed outer JSON only.
Mock failures cover exited-root/live-descendant ownership, timeout, assignment,
and termination error paths. Actual Windows nested-job assignment, unwind and
cleanup responsiveness remain HOSTED runtime checks, NOT claimed from mocks or
source. There is no static hard guarantee against unresponsive kernel operations.
