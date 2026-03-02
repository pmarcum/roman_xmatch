"""
roman_xmatch.catalogs
=====================
Catalog loaders.  Each function loads a pre-built catalog file that ships
with the roman-xmatch package and returns an astropy Table with at minimum
the columns:  RA, Dec, catalog, object_id.

Pre-built catalog files live in roman_xmatch/data/*.fits.gz and are
generated once by running:

    python scripts/build_catalogs.py

Supported catalogs
------------------
  abell            — Abell clusters of galaxies         (VizieR VII/110A)
  chandra-clusters — MCXC X-ray galaxy clusters         (VizieR J/A+A/534/A109)
  sdss             — SDSS DR18 photometric galaxies      (SkyServer, type=3)
  2masx            — 2MASS Extended Source Catalog       (VizieR VII/233)
  ngc_ugc          — NGC/IC + UGC galaxies               (VizieR VII/118 + VII/26D)
  xray_gal         — X-ray galaxies, CSC + XMM validated (CXC + VizieR IX/69)
  custom           — User-supplied FITS or CSV file
"""

from __future__ import annotations

import os
import warnings
import numpy as np
import pandas as pd
from astropy.table import Table

warnings.filterwarnings("ignore")

from .cache import load_bundled


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

CATALOG_KEYS = [
    "abell",
    "chandra-clusters",
    "sdss",
    "2masx",
    "ngc_ugc",
    "xray_gal",
    "custom",
]

CATALOG_LABELS = {
    "abell":            "Abell Clusters (VizieR VII/110A)",
    "chandra-clusters": "Chandra Galaxy Clusters — MCXC (VizieR J/A+A/534/A109)",
    "sdss":             "SDSS Photometric Galaxies DR18 (SkyServer)",
    "2masx":            "2MASS Extended Source Catalog (VizieR VII/233)",
    "ngc_ugc":          "NGC/IC + UGC Galaxies (VizieR VII/118 + VII/26D)",
    "xray_gal":         "X-ray Galaxies — Chandra CSC 2.1 + XMM 4XMM-DR13",
    "custom":           "Custom user file (FITS or CSV)",
}


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def fetch_catalog(
    catalog_key: str,
    row_limit: int = 100_000,
    footprint: dict = None,
    healpix_mask=None,
    healpix_nside: int = None,
    custom_file: str = None,
    custom_ra_col: str = "RA",
    custom_dec_col: str = "Dec",
    progress_callback=None,
) -> Table | None:
    """
    Load a catalog and return an astropy Table, or None on failure.

    For all standard catalogs this simply reads the pre-built .fits.gz file
    that ships with the package.  Footprint filtering is handled downstream
    in pipeline.py — the full catalog is always returned here.

    Parameters
    ----------
    catalog_key      : one of CATALOG_KEYS
    row_limit        : ignored for bundled catalogs (kept for API compatibility)
    footprint        : ignored for bundled catalogs (kept for API compatibility)
    healpix_mask     : ignored for bundled catalogs (kept for API compatibility)
    healpix_nside    : ignored for bundled catalogs (kept for API compatibility)
    custom_file      : path to user catalog (required if catalog_key == 'custom')
    custom_ra_col    : RA column name in custom file
    custom_dec_col   : Dec column name in custom file
    progress_callback: optional callable(message: str) for GUI status updates
    """
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    key = catalog_key.lower()

    if key == "custom":
        return _fetch_custom(custom_file, custom_ra_col, custom_dec_col, log)

    # All other catalogs load from bundled files
    bundle_name = "mcxc" if key == "chandra-clusters" else key

    label = CATALOG_LABELS.get(key, key)
    log(f"Loading {label}…")
    try:
        t = load_bundled(bundle_name)
        log(f"  {len(t):,} sources loaded.")
        return t
    except FileNotFoundError as exc:
        log(f"ERROR: {exc}")
        return None
    except Exception as exc:
        log(f"ERROR loading bundled catalog '{bundle_name}': {exc}")
        return None


# ---------------------------------------------------------------------------
# Custom catalog loader (still reads from user-supplied file at runtime)
# ---------------------------------------------------------------------------

def _standardise(table: Table, ra_col: str, dec_col: str,
                 catalog_tag: str, id_col: str = None) -> Table:
    """Rename RA/Dec columns, force float64, add catalog + object_id."""
    if ra_col in table.colnames and ra_col != "RA":
        table.rename_column(ra_col, "RA")
    if dec_col in table.colnames and dec_col != "Dec":
        table.rename_column(dec_col, "Dec")

    from astropy.coordinates import Angle
    for col in ["RA", "Dec"]:
        if col not in table.colnames:
            continue
        try:
            vals = np.array(table[col], dtype=float)
        except (ValueError, TypeError):
            raw = [str(v) for v in table[col]]
            if col == "RA":
                vals = np.array([Angle(v, unit="hourangle").deg for v in raw])
            else:
                vals = np.array([Angle(v, unit="deg").deg for v in raw])
        table[col] = vals

    if "RA" in table.colnames and "Dec" in table.colnames:
        good = np.isfinite(table["RA"]) & np.isfinite(table["Dec"])
        table = table[good]

    table["catalog"] = catalog_tag
    if id_col and id_col in table.colnames:
        table["object_id"] = [str(r[id_col]) for r in table]
    else:
        table["object_id"] = [f"{catalog_tag}_{i}" for i in range(len(table))]
    return table


def _fetch_custom(
    file_path: str,
    ra_col: str,
    dec_col: str,
    log,
) -> Table | None:
    """Load a user-supplied FITS or CSV catalog."""
    if not file_path:
        log("ERROR: No custom file path provided.")
        return None
    if not os.path.exists(file_path):
        log(f"ERROR: Custom file not found: {file_path}")
        return None

    log(f"Loading custom catalog: {file_path}")
    try:
        if file_path.lower().endswith((".fits", ".fit")):
            t = Table.read(file_path, format="fits")
        elif file_path.lower().endswith(".csv"):
            t = Table.from_pandas(pd.read_csv(file_path))
        else:
            try:
                t = Table.read(file_path)
            except Exception:
                t = Table.from_pandas(pd.read_csv(file_path))
    except Exception as exc:
        log(f"ERROR: Could not read custom file: {exc}")
        return None

    if ra_col not in t.colnames or dec_col not in t.colnames:
        log(
            f"ERROR: Columns '{ra_col}' / '{dec_col}' not found in custom file.\n"
            f"       Available columns: {t.colnames}"
        )
        return None

    return _standardise(t, ra_col, dec_col, "Custom")
