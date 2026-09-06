"""SI solar-system laboratory. Not the toy WorldScene plate.

State is metres, kilograms, seconds. The camera is an observer, not a
body: physics always runs; `observe.py` decides whether the plate would
notice — every body, orbit and IAU spin. Hands do not write a fake z
into the ODE.
"""
