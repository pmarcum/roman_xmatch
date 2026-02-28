"""
tests/test_basic.py
===================
Smoke tests — no network required.
"""

import numpy as np
import pytest

from roman_xmatch.footprints import get_footprint, SURVEY_KEYS
from roman_xmatch.crossmatch import points_in_footprint


# ---------------------------------------------------------------------------
# Footprint smoke tests
# ---------------------------------------------------------------------------

def test_all_surveys_load():
    for key in SURVEY_KEYS:
        fp = get_footprint(key)
        assert "name" in fp
        assert "type" in fp


def test_unknown_survey_raises():
    with pytest.raises(ValueError):
        get_footprint("bogus")


# ---------------------------------------------------------------------------
# HLWAS sky-cut tests
# ---------------------------------------------------------------------------

HLWAS = get_footprint("hlwas")

def test_hlwas_high_galactic_lat():
    # RA=150, Dec=-30 — safely away from the Galactic plane → should be inside
    inside = points_in_footprint([150.0], [-30.0], HLWAS)
    assert inside[0], "Expected RA=150, Dec=-30 to be inside HLWAS"


def test_hlwas_galactic_plane_excluded():
    # Galactic centre direction — should be outside
    inside = points_in_footprint([266.4], [-28.9], HLWAS)
    assert not inside[0], "Galactic centre direction should be outside HLWAS"


def test_hlwas_north_pole_excluded():
    # Dec=+89 — above the Dec cut
    inside = points_in_footprint([0.0], [89.0], HLWAS)
    assert not inside[0], "North celestial pole should be outside HLWAS"


def test_hlwas_array_input():
    ra  = np.array([150.0, 266.4, 0.0])
    dec = np.array([-30.0, -28.9, 89.0])
    inside = points_in_footprint(ra, dec, HLWAS)
    assert inside[0]  and not inside[1] and not inside[2]


# ---------------------------------------------------------------------------
# HLTDS circle tests
# ---------------------------------------------------------------------------

HLTDS = get_footprint("hltds")

def test_hltds_field_centres_inside():
    # Field centres should definitely be inside
    ra  = [242.75, 59.10]
    dec = [54.98, -49.32]
    inside = points_in_footprint(ra, dec, HLTDS)
    assert all(inside), "HLTDS field centres should be inside footprint"


def test_hltds_far_point_outside():
    # Random far-away point
    inside = points_in_footprint([0.0], [0.0], HLTDS)
    assert not inside[0], "RA=0, Dec=0 should be outside HLTDS"


# ---------------------------------------------------------------------------
# GBTDS circle tests
# ---------------------------------------------------------------------------

GBTDS = get_footprint("gbtds")

def test_gbtds_has_six_fields():
    assert len(GBTDS["fields"]) == 6


def test_gbtds_field_centres_inside():
    ra  = [f["ra"]  for f in GBTDS["fields"]]
    dec = [f["dec"] for f in GBTDS["fields"]]
    inside = points_in_footprint(ra, dec, GBTDS)
    assert all(inside), "All GBTDS field centres should be inside footprint"


def test_gbtds_north_pole_outside():
    inside = points_in_footprint([0.0], [89.0], GBTDS)
    assert not inside[0]
