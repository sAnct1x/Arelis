"""Published constants for the units tool — cited, not measured this turn.

Values are from public CODATA / IAU / cosmology papers. The tool result must
name the source and year so a 9B cannot present them as a measurement it just
made. Hubble's constant is two published figures plus the tension, not a gavel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishedConstant:
    id: str
    name: str
    value: float
    unit: str
    source: str
    notes: str = ""


# CODATA 2022 defining / derived SI constants (NIST).
# G keeps its experimental uncertainty; most others below are exact in SI.
_CODATA_2022: tuple[PublishedConstant, ...] = (
    PublishedConstant(
        "c",
        "speed of light in vacuum",
        299_792_458.0,
        "m/s",
        "CODATA 2022",
        "Exact (SI defining).",
    ),
    PublishedConstant(
        "G",
        "Newtonian constant of gravitation",
        6.67430e-11,
        "m**3 / kg / s**2",
        "CODATA 2022",
        "Standard uncertainty 0.00015e-11.",
    ),
    PublishedConstant(
        "h",
        "Planck constant",
        6.62607015e-34,
        "J*s",
        "CODATA 2022",
        "Exact (SI defining).",
    ),
    PublishedConstant(
        "hbar",
        "reduced Planck constant",
        1.054571817e-34,
        "J*s",
        "CODATA 2022",
        "Exact given h (h/2π).",
    ),
    PublishedConstant(
        "e",
        "elementary charge",
        1.602176634e-19,
        "C",
        "CODATA 2022",
        "Exact (SI defining).",
    ),
    PublishedConstant(
        "k",
        "Boltzmann constant",
        1.380649e-23,
        "J/K",
        "CODATA 2022",
        "Exact (SI defining).",
    ),
    PublishedConstant(
        "N_A",
        "Avogadro constant",
        6.02214076e23,
        "1/mol",
        "CODATA 2022",
        "Exact (SI defining).",
    ),
    PublishedConstant(
        "R",
        "molar gas constant",
        8.314462618,
        "J / (mol * K)",
        "CODATA 2022",
        "Exact given k and N_A.",
    ),
    PublishedConstant(
        "sigma",
        "Stefan-Boltzmann constant",
        5.670374419e-8,
        "W / (m**2 * K**4)",
        "CODATA 2022",
        "Exact given other SI defining constants.",
    ),
)

# IAU 2015 nominal values (not a mass measurement this turn).
_IAU_2015: tuple[PublishedConstant, ...] = (
    PublishedConstant(
        "au",
        "astronomical unit",
        149_597_870_700.0,
        "m",
        "IAU 2012 / IAU 2015",
        "Exact by definition.",
    ),
    PublishedConstant(
        "pc",
        "parsec",
        3.0856775814913673e16,
        "m",
        "IAU 2015",
        "Derived from the astronomical unit.",
    ),
    PublishedConstant(
        "R_sun",
        "nominal solar radius",
        6.957e8,
        "m",
        "IAU 2015",
        "Nominal, not a new measurement.",
    ),
    PublishedConstant(
        "M_sun",
        "solar mass",
        1.98847e30,
        "kg",
        "IAU 2015 (nominal, via GM_sun)",
        "Use as an order-of-magnitude mass, not a lab weighing.",
    ),
    PublishedConstant(
        "L_sun",
        "nominal solar luminosity",
        3.828e26,
        "W",
        "IAU 2015",
        "Nominal.",
    ),
)

_COSMO: tuple[PublishedConstant, ...] = (
    PublishedConstant(
        "T_cmb",
        "CMB monopole temperature",
        2.7255,
        "K",
        "Fixsen 2009 / Planck",
        "Published sky average, not measured this turn.",
    ),
    PublishedConstant(
        "v_cmb",
        "CMB dipole speed relative to the Sun",
        369.82,
        "km/s",
        "Planck 2018",
        "A boost, not a unit conversion. Direction omitted on purpose.",
    ),
    PublishedConstant(
        "H0_planck",
        "Hubble constant (Planck 2018 CMB)",
        67.4,
        "km / s / Mpc",
        "Planck 2018",
        "One published figure. Local distance-ladder values differ (tension).",
    ),
    PublishedConstant(
        "H0_sh0es",
        "Hubble constant (SH0ES local distance ladder)",
        73.04,
        "km / s / Mpc",
        "Riess et al. SH0ES (2022 vintage in common use)",
        "The other common published figure. Not a verdict on the tension.",
    ),
)

CONSTANTS: dict[str, PublishedConstant] = {
    item.id: item for item in (*_CODATA_2022, *_IAU_2015, *_COSMO)
}

_ALIASES: dict[str, str] = {
    "speed of light": "c",
    "speed of light in vacuum": "c",
    "gravitational constant": "G",
    "newtonian constant": "G",
    "newton's constant": "G",
    "newtonian constant of gravitation": "G",
    "planck constant": "h",
    "planck's constant": "h",
    "reduced planck": "hbar",
    "hbar": "hbar",
    "h-bar": "hbar",
    "elementary charge": "e",
    "electron charge": "e",
    "boltzmann": "k",
    "boltzmann constant": "k",
    "avogadro": "N_A",
    "avogadro constant": "N_A",
    "avogadro's number": "N_A",
    "gas constant": "R",
    "molar gas constant": "R",
    "stefan-boltzmann": "sigma",
    "stefan boltzmann": "sigma",
    "stefan-boltzmann constant": "sigma",
    "astronomical unit": "au",
    "parsec": "pc",
    "solar radius": "R_sun",
    "solar mass": "M_sun",
    "solar luminosity": "L_sun",
    "cmb temperature": "T_cmb",
    "cmb monopole": "T_cmb",
    "t_cmb": "T_cmb",
    "cmb dipole": "v_cmb",
    "hubble": "H0_planck",
    "hubble constant": "H0_planck",
    "h0": "H0_planck",
}


def lookup_constant(name: str) -> PublishedConstant | tuple[PublishedConstant, ...] | None:
    """Resolve a spoken or id name. Hubble returns both published figures."""
    raw = (name or "").strip()
    if not raw:
        return None
    key = raw.replace("'", "").replace("\u2019", "")
    lowered = " ".join(key.lower().split())
    ident = CONSTANTS.get(key) or CONSTANTS.get(lowered)
    if ident is not None:
        if ident.id in {"H0_planck", "H0_sh0es"}:
            return (CONSTANTS["H0_planck"], CONSTANTS["H0_sh0es"])
        return ident
    aliased = _ALIASES.get(lowered)
    if aliased == "H0_planck":
        return (CONSTANTS["H0_planck"], CONSTANTS["H0_sh0es"])
    if aliased and aliased in CONSTANTS:
        return CONSTANTS[aliased]
    compact = lowered.replace(" ", "_")
    if compact in CONSTANTS:
        return CONSTANTS[compact]
    return None


def format_constant(item: PublishedConstant) -> str:
    """One line a model can quote without sounding like it measured it."""
    note = f" {item.notes}" if item.notes else ""
    return (
        f"{item.name} ({item.id}) = {item.value} {item.unit} "
        f"— source: {item.source}; not measured this turn.{note}"
    )
