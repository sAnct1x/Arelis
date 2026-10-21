"""Model setup is not a first-run step.

Chat is llama.cpp. This module stays so launch can import the old name.
"""

from __future__ import annotations


def prompt_for_model_setup(parent: object | None = None) -> str | None:
    """No model dialog. First-run only asks for a workspace folder."""
    del parent
    return None
