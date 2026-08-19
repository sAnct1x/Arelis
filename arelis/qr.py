"""QR modules for the phone pairing ticket.

Generated locally with segno — no network. The old hand-rolled encoder
looked like a QR (finders were in the right corners) but scanners would
not decode it.
"""

from __future__ import annotations

import segno


def qr_modules(text: str) -> list[list[bool]]:
    """Return a square matrix, True = dark module, including quiet zone of 4."""
    qr = segno.make(text, error="m", boost_error=False)
    border = 4
    core = qr.matrix
    n = len(core)
    side = n + 2 * border
    out = [[False] * side for _ in range(side)]
    for r, row in enumerate(core):
        for c, cell in enumerate(row):
            out[r + border][c + border] = bool(cell)
    return out


def qr_has_finders(modules: list[list[bool]]) -> bool:
    """True when the three finder squares are dark-bordered after the quiet zone."""
    q = 4
    n = len(modules) - 2 * q
    if n < 21:
        return False
    for r0, c0 in ((q, q), (q, q + n - 7), (q + n - 7, q)):
        if not modules[r0][c0] or not modules[r0 + 6][c0 + 6]:
            return False
        if modules[r0 + 1][c0 + 1]:
            return False
    return True
