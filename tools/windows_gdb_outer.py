"""Temporary hosted-only Job Object supervisor; no debugger capture implementation."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

from arelis.tools import child_proc


class OwnedJob:
    def __init__(self):
        self.kernel = child_proc._kernel32()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if child_proc._bad_handle(self.handle):
            raise OSError
        try:
            limits = child_proc._extended_limit_info()
            # A NEW diagnostic job, not the product cell's active-process limit.
            limits.BasicLimitInformation.LimitFlags = child_proc._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise OSError
            from ctypes import wintypes

            self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel.TerminateJobObject.restype = wintypes.BOOL
            self.kernel.QueryInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.LPVOID,
            ]
            self.kernel.QueryInformationJobObject.restype = wintypes.BOOL
        except BaseException:
            self.close()
            raise

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError

    def empty(self):
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_int64 * 4), ("counts", ctypes.c_uint32 * 4)]

        info = Accounting()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            raise OSError
        return info.counts[2] == 0  # ActiveProcesses; never emit IDs or handles.

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise OSError

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise OSError


def supervise(job_factory=OwnedJob, spawn=subprocess.Popen):
    result = {"status": "failed", "phase": "outer_start", "owned_empty": False}
    job = None
    process = None
    assigned = False
    code = 1
    try:
        job = job_factory()
        python, env = child_proc._windows_cell_python(sys.executable, dict(os.environ))
        process = spawn(
            [python, "-m", "tools.windows_gdb_validation", "--hosted-windows-proof", "--job-gated"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=subprocess.DEVNULL,
        )
        # Root waits on private stdin before it can create GDB or Qt descendants.
        job.assign(process)
        assigned = True
        process.stdin.write(b"go\n")
        process.stdin.flush()
        result["phase"] = "outer_wait"
        code = process.wait(timeout=35)
    except Exception:
        code = 1
    finally:
        # Job ownership survives root exit; NEVER gate cleanup on root.poll().
        if job is not None:
            try:
                if not job.empty():
                    code = 1  # Leftovers cannot count as a normally exited proof.
            except Exception:
                code = 1
            try:
                job.terminate()
                deadline = time.monotonic() + 2
                while not job.empty():
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                    time.sleep(0.02)
                result["owned_empty"] = True
            except Exception:
                code = 1
            finally:
                try:
                    job.close()  # kill-on-close even if terminate/query failed
                except Exception:
                    code = 1
        if process is not None and not assigned:
            # Gate was never released: this root cannot have spawned descendants.
            try:
                process.kill()
                process.wait(timeout=1)
            except Exception:
                code = 1
    result["status"] = "passed" if code == 0 and result["owned_empty"] else "failed"
    return result


if __name__ == "__main__":
    report = {"status": "failed", "phase": "outer_preflight"}
    try:
        if (
            sys.platform == "win32"
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_OS") == "Windows"
        ):
            report = supervise()
    except BaseException:
        report = {"status": "failed", "phase": "outer_internal_error"}
    print(json.dumps(report, sort_keys=True), flush=True)
    sys.exit(0 if report["status"] == "passed" else 1)
