"""
roman_xmatch.footprints
=======================
Survey footprint definitions for the Roman Space Telescope.

Each get_*_footprint() function returns a dict describing the geometry of
a Core Community Survey.  The dict is consumed by crossmatch.points_in_footprint().

Sources
-------
ROTAC Final Report, April 2025 — https://roman.ipac.caltech.edu/page/core-community-surveys
"""

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, Galactic

# ---------------------------------------------------------------------------
# Public registry — consumed by CLI, GUI, and crossmatch engine
# ---------------------------------------------------------------------------

SURVEY_KEYS = ["hlwas", "hltds", "gbtds"]

SURVEY_LABELS = {
    "hlwas": "HLWAS — High Latitude Wide Area Survey (~5,000 deg²)",
    "hltds": "HLTDS — High Latitude Time Domain Survey (~18 deg²)",
    "gbtds": "GBTDS — Galactic Bulge Time Domain Survey (~2 deg²)",
}


def get_footprint(survey_key: str) -> dict:
    """Return the footprint dict for the given survey key (case-insensitive)."""
    key = survey_key.lower()
    if key == "hlwas":
        return get_hlwas_footprint()
    if key == "hltds":
        return get_hltds_footprint()
    if key == "gbtds":
        return get_gbtds_footprint()
    raise ValueError(
        f"Unknown survey '{survey_key}'. "
        f"Choose from: {SURVEY_KEYS}"
    )


# ---------------------------------------------------------------------------
# Individual footprint definitions
# ---------------------------------------------------------------------------

def get_hlwas_footprint() -> dict:
    """
    High Latitude Wide Area Survey (~5,000 deg²).

    The ROTAC-recommended footprint avoids the Galactic plane (|b| > ~20°)
    and Ecliptic plane (|ecl_lat| > ~15°), and is placed predominantly in
    the southern sky to maximise overlap with Rubin/LSST.

    Approximated here with sky cuts:
      |b|       > 20°   (Galactic latitude)
      |ecl_lat| > 15°   (Ecliptic latitude)
      Dec       < +30°  (southern-hemisphere bias)

    Reference: ROTAC Final Report (April 2025)
    """
    return {
        "name":        "HLWAS",
        "description": "High Latitude Wide Area Survey (~5,000 deg²)",
        "type":        "sky_cuts",
        "gal_lat_min": 20.0,   # degrees — |b| must exceed this
        "ecl_lat_min": 15.0,   # degrees — |ecliptic lat| must exceed this
        "dec_max":     30.0,   # degrees — Dec must be below this
        "area_deg2":   5000,
    }


def get_hltds_footprint() -> dict:
    """
    High Latitude Time Domain Survey (~18 deg²).

    Two discrete fields from the ROTAC in-guide survey (April 2025):
      North : ELAIS-N1  RA=242.75°, Dec=+54.98°
      South : EDFS      RA= 59.10°, Dec=−49.32°

    Each modelled as a circular cap of radius 2.4° (~9 deg² each).
    """
    return {
        "name":        "HLTDS",
        "description": "High Latitude Time Domain Survey (~18 deg², 2 fields)",
        "type":        "circles",
        "fields": [
            {"label": "ELAIS-N1 (North)", "ra": 242.75, "dec":  54.98, "radius_deg": 2.4},
            {"label": "EDFS (South)",     "ra":  59.10, "dec": -49.32, "radius_deg": 2.4},
        ],
    }


def get_gbtds_footprint() -> dict:
    """
    Galactic Bulge Time Domain Survey (~2 deg²).

    Six WFI pointings toward the Galactic bulge (ROTAC Final Report, 2025).
    Field centres in Galactic (l, b) — converted here to ICRS.

    Fields 1–5 : l = −0.418, −0.009, 0.400, 0.809, 1.218;  b = −1.200
    Field  6   : l =  0.000,                                 b = −0.125
    """
    pointing_lb = [
        (-0.418, -1.200),
        (-0.009, -1.200),
        ( 0.400, -1.200),
        ( 0.809, -1.200),
        ( 1.218, -1.200),
        ( 0.000, -0.125),
    ]
    gal_coords = SkyCoord(
        l=[p[0] for p in pointing_lb] * u.deg,
        b=[p[1] for p in pointing_lb] * u.deg,
        frame=Galactic,
    ).icrs

    fields = []
    for i, c in enumerate(gal_coords):
        fields.append({
            "label":      f"GBTDS Field {i+1}  (l={pointing_lb[i][0]:.3f}, b={pointing_lb[i][1]:.3f})",
            "ra":         c.ra.deg,
            "dec":        c.dec.deg,
            "radius_deg": 0.30,   # slightly larger than WFI FOV to allow dither overlap
        })

    return {
        "name":        "GBTDS",
        "description": "Galactic Bulge Time Domain Survey (~2 deg², 6 pointings)",
        "type":        "circles",
        "fields":      fields,
    }
