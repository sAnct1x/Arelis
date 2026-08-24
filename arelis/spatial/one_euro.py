"""1€ filter (Casiez, Roussel, Vogel, CHI 2012).

Speed-dependent low-pass: still signals lose jitter, fast signals lose lag.
Two knobs. No Kalman pile until this is measured on a take.
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
