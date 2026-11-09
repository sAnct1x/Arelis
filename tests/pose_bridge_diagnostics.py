"""Test-only Node progress on stderr; stdout, native exit and30s bound unchanged."""

import subprocess

from tests.overseer_render_diagnostics import sanitize

NODE_MARKERS = r"""const __poseDiagnosticFS = require('fs');
function __poseDiagnostic(phase, resources = false, code) {
  const row = {event: 'pose-bridge', phase};
  if (phase === 'entry') { row.pid = process.pid; row.node = process.version; }
  if (Number.isInteger(code)) row.code = code;
  if (resources) {
    row.resourceTypes = typeof process.getActiveResourcesInfo === 'function'
      ? process.getActiveResourcesInfo().slice(0, 16).map(
          t => String(t).replace(/[^A-Za-z0-9_-]/g, '?').slice(0, 48))
      : 'unavailable';
  }
  __poseDiagnosticFS.writeSync(2, JSON.stringify(row) + '\n');
}
__poseDiagnostic('entry');
process.once('beforeExit', code => __poseDiagnostic('before-exit', true, code));
process.once('exit', code => __poseDiagnostic('exit', false, code));
"""


def run_bridge(script):
    try:
        return subprocess.run(
            ["node", str(script)], capture_output=True, text=True, timeout=30, check=True
        )
    except subprocess.TimeoutExpired as exc:

        def partial(value):
            # Prefix only: never start in the middle of a credential assignment.
            value = value[:4096] if value is not None else "<unavailable>"
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            return sanitize(value)[:4096]

        exc.add_note(
            "Node bridge timed out; original deadline/verdict unchanged.\n"
            f"stdout prefix: {partial(exc.stdout)}\nstderr prefix: {partial(exc.stderr)}"
        )
        raise
