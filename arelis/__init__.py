"""Arelis, local-first personal research assistant.

The three facts the application states about itself live here, and nowhere
else. `pyproject.toml` reads `__version__` from this file rather than carrying
its own copy, because two version numbers stay equal only for as long as
somebody remembers to change both, and the one a user is shown should be the
one the package actually is.
"""

__version__ = "0.3.3"

# SPDX identifier. The full text is in LICENSE at the root of the repository.
__license__ = "AGPL-3.0-or-later"

# Where a user can get the source. The AGPL is only meaningful if the person
# running the program can find what they are entitled to, so this is shown in
# the app rather than buried in a file most people never open.
__source_url__ = "https://github.com/sAnct1x/arelis"


def _cap_math_threads() -> None:
    """Keep numpy's BLAS / OpenMP pools small before anything imports them.

    OpenBLAS starts one thread per core and spins them after each call, which on
    Atria competed with llama-server's decode threads while she streams. Our math is
    small; two threads lose nothing. A value the user set wins.
    """
    import os

    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(key, "2")


_cap_math_threads()
