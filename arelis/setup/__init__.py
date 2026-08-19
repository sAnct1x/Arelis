"""First-run model setup: look at this PC, recommend one brain, pull it.

The workspace folder is still the only permission asked up front. This package
is the next glass: hardware, one recommended chat model, a short why, confirm
or pick another. One model at a time. No toys. No cloud tags.
"""

from arelis.setup.catalog import CATALOG, CatalogModel, recommend, why
from arelis.setup.hardware import HardwareSnapshot, probe_hardware
from arelis.setup.state import needs_model_setup, record_model_choice

__all__ = [
    "CATALOG",
    "CatalogModel",
    "HardwareSnapshot",
    "needs_model_setup",
    "probe_hardware",
    "recommend",
    "record_model_choice",
    "why",
]
