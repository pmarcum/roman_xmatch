"""
roman_xmatch.crossmatch
=======================
Footprint membership tests.

The central function points_in_footprint() accepts arrays of (RA, Dec) and
a footprint dict (from roman_xmatch.footprints) and returns a boolean mask
indicating which points lie inside the survey area.

Supports:
  - Built-in sky-cut approximations (HLWAS)
  - Circular / discrete field footprints (HLTDS, GBTDS)
  - External HEALPix FITS mask files (any survey, when available)
"""

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, BarycentricTrueEcliptic

# healpy is optional — only needed for external mask files
try:
    import healpy as hp
    HAS_HEALPY = True
except ImportError:
    HAS_HEALPY = False


# ---------------------------------------------------------------------------
# HEALPix mask I/O
# ---------------------------------------------------------------------------

def load_healpix_mask(mask_path: str):
    """
    Load a HEALPix mask FITS file.

    Returns
    -------
    hpmap : 1-D ndarray  — pixel values (> 0 means inside footprint)
    nside : int          — HEALPix resolution parameter
    """
    if not HAS_HEALPY:
        raise RuntimeError(
            "healpy is required to read HEALPix mask files.\n"
            "Install it with:  pip install healpy"
        )
    hpmap = hp.read_map(mask_path, verbose=False)
    nside = hp.npix2nside(len(hpmap))
    return hpmap, nside


# ---------------------------------------------------------------------------
# Core membership test
# ---------------------------------------------------------------------------

def points_in_footprint(
    ra_arr,
    dec_arr,
    footprint: dict,
    healpix_mask=None,
    healpix_nside: int = None,
) -> np.ndarray:
    """
    Test whether arrays of (RA, Dec) sky positions lie inside a survey footprint.

    Parameters
    ----------
    ra_arr, dec_arr : array-like
        Right Ascension and Declination in decimal degrees (J2000 / ICRS).
    footprint : dict
        A footprint definition dict from roman_xmatch.footprints.
    healpix_mask : 1-D ndarray, optional
        HEALPix map loaded by load_healpix_mask().  Pixels with value > 0
        are considered inside the footprint.  When provided, overrides the
        built-in geometry entirely.
    healpix_nside : int, optional
        nside parameter matching healpix_mask.

    Returns
    -------
    inside : ndarray of bool
        True for every point that lies inside the footprint.
    """
    ra_arr  = np.asarray(ra_arr,  dtype=float)
    dec_arr = np.asarray(dec_arr, dtype=float)

    # ------------------------------------------------------------------
    # 1.  External HEALPix mask — highest priority
    # ------------------------------------------------------------------
    if healpix_mask is not None:
        if not HAS_HEALPY:
            raise RuntimeError("healpy is required to use a HEALPix mask.")
        theta = np.radians(90.0 - dec_arr)
        phi   = np.radians(ra_arr)
        pix   = hp.ang2pix(healpix_nside, theta, phi)
        return healpix_mask[pix] > 0

    ftype = footprint["type"]

    # ------------------------------------------------------------------
    # 2.  Circular / discrete-field footprint  (HLTDS, GBTDS)
    # ------------------------------------------------------------------
    if ftype == "circles":
        coords = SkyCoord(ra=ra_arr * u.deg, dec=dec_arr * u.deg, frame="icrs")
        inside = np.zeros(len(ra_arr), dtype=bool)
        for field in footprint["fields"]:
            centre = SkyCoord(
                ra=field["ra"] * u.deg,
                dec=field["dec"] * u.deg,
                frame="icrs",
            )
            inside |= coords.separation(centre).deg <= field["radius_deg"]
        return inside

    # ------------------------------------------------------------------
    # 3.  Sky-cut approximation  (HLWAS)
    # ------------------------------------------------------------------
    if ftype == "sky_cuts":
        coords  = SkyCoord(ra=ra_arr * u.deg, dec=dec_arr * u.deg, frame="icrs")
        gal_lat = np.abs(coords.galactic.b.deg)
        ecl_lat = np.abs(
            coords.transform_to(BarycentricTrueEcliptic()).lat.deg
        )
        return (
            (gal_lat  >= footprint["gal_lat_min"])
            & (ecl_lat >= footprint["ecl_lat_min"])
            & (dec_arr <= footprint["dec_max"])
        )

    raise ValueError(f"Unknown footprint type: '{ftype}'")
