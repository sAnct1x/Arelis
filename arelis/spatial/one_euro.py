"""1€ filter (Casiez, Roussel, Vogel, CHI 2012).

Speed-dependent low-pass: still signals lose jitter, fast signals lose lag.
Two knobs. No Kalman pile until this is measured on a take.

beta is "Hz per unit of speed", and speed is in the same units as the
signal. The paper's 0.007 is a pixel demo (~1000 px/s). A hand on this
camera is 0–1, and a cross of the frame is a few units per second, so
0.007 never opens the filter — the cursor sits on a ~160 ms low-pass
whether the hand is still or not.
"""

from __future__ import annotations

import math


class _LowPass:
    def __init__(self) -> None:
        self._hat = 0.0
        self._has = False

    def filter(self, value: float, alpha: float) -> float:
        if not self._has:
            self._hat = value
            self._has = True
            return value
        self._hat = alpha * value + (1.0 - alpha) * self._hat
        return self._hat

    def reset(self) -> None:
        self._hat = 0.0
        self._has = False


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class OneEuro:
    """Scalar 1€. Call with (value, time_seconds)."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.007,
        d_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x = _LowPass()
        self._dx = _LowPass()
        self._t: float | None = None

    def reset(self) -> None:
        self._x.reset()
        self._dx.reset()
        self._t = None

    def __call__(self, value: float, t: float) -> float:
        if self._t is None:
            self._t = t
            return self._x.filter(value, 1.0)
        dt = max(t - self._t, 1e-6)
        self._t = t
        prev = self._x._hat if self._x._has else value
        dx = (value - prev) / dt
        edx = self._dx.filter(dx, _alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x.filter(value, _alpha(cutoff, dt))


def depth_euro() -> OneEuro:
    """1€ for world z. The cursor's beta snaps a bad span to the far wall."""
    return OneEuro(min_cutoff=1.0, beta=4.0, d_cutoff=1.0)


def hand_euro() -> OneEuro:
    """1€ for a 0–1 image or world axis at camera rate.

    min_cutoff stays ~1 Hz so a still hand does not buzz. beta=30 raises
    the cutoff to ~10 Hz on a deliberate move (~0.3 /s) and essentially
    turns the filter off on a flick, which is what 0.007 does in pixels.
    """
    return OneEuro(min_cutoff=1.0, beta=30.0, d_cutoff=1.0)
