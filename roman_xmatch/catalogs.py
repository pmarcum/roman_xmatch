"""
roman_xmatch.catalogs
=====================
Catalog fetchers.  Each function queries a remote data service and returns
an astropy Table with at minimum the columns  RA, Dec, catalog, object_id.

Supported catalogs
------------------
  abell   — Abell clusters of galaxies         (VizieR VII/110A)
  sdss    — SDSS photometric objects DR7        (VizieR II/294)
  2masx   — 2MASS Extended Source Catalog       (VizieR VII/233)
  ngc     — NGC/IC catalog                      (VizieR VII/118)
  ned     — NASA/IPAC Extragalactic Database    (astroquery.ipac.ned)
  custom  — User-supplied FITS or CSV file
"""

import os
import warnings
import numpy as np
import pandas as pd
from astropy.table import Table, vstack
import astropy.units as u
from astropy.coordinates import SkyCoord

warnings.filterwarnings("ignore")

from astroquery.vizier import Vizier
from astroquery.ipac.ned import Ned

from .crossmatch import points_in_footprint


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

CATALOG_KEYS   = ["abell", "sdss", "2masx", "ngc", "ned", "custom"]
CATALOG_LABELS = {
    "abell":  "Abell Clusters (VizieR VII/110A)",
    "sdss":   "SDSS Photometric Catalog DR7 (VizieR II/294)",
    "2masx":  "2MASS Extended Source Catalog (VizieR VII/233)",
    "ngc":    "NGC/IC Catalog (VizieR VII/118)",
    "ned":    "NED — NASA/IPAC Extragalactic Database",
    "custom": "Custom user file (FITS or CSV)",
}


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
    Unified entry point.  Returns an astropy Table or None on failure.

    Parameters
    ----------
    catalog_key      : one of CATALOG_KEYS
    row_limit        : maximum rows to retrieve from VizieR/NED
    footprint        : footprint dict — required for NED tiling strategy
    healpix_mask     : optional HEALPix map array
    healpix_nside    : nside matching healpix_mask
    custom_file      : path to user catalog (required if catalog_key=="custom")
    custom_ra_col    : RA column name in custom file
    custom_dec_col   : Dec column name in custom file
    progress_callback: optional callable(message: str) for GUI status updates
    """
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    key = catalog_key.lower()

    if key == "abell":
        return _fetch_abell(row_limit, log)
    if key == "sdss":
        return _fetch_sdss(row_limit, log)
    if key == "2masx":
        return _fetch_2masx(row_limit, log)
    if key == "ngc":
        return _fetch_ngc(row_limit, log)
    if key == "ned":
        return _fetch_ned(footprint, healpix_mask, healpix_nside, row_limit, log)
    if key == "custom":
        return _fetch_custom(custom_file, custom_ra_col, custom_dec_col, log)

    raise ValueError(f"Unknown catalog key '{catalog_key}'. Choose from: {CATALOG_KEYS}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _vizier_query(catalog_id: str, columns: list, row_limit: int) -> Table | None:
    """Fetch an entire VizieR catalog up to row_limit rows."""
    v = Vizier(columns=columns, row_limit=row_limit)
    result = v.get_catalogs(catalog_id)
    if not result:
        return None
    return result[0]


def _standardise(table: Table, ra_col: str, dec_col: str,
                 catalog_tag: str, id_col: str = None) -> Table:
    """
    Rename RA/Dec columns, force them to plain float64, and add
    catalog + object_id columns.

    VizieR sometimes returns masked or structured columns; converting to
    plain numpy float arrays avoids downstream KeyError / attribute errors.
    """
    # Rename to standard names
    if ra_col in table.colnames and ra_col != "RA":
        table.rename_column(ra_col, "RA")
    if dec_col in table.colnames and dec_col != "Dec":
        table.rename_column(dec_col, "Dec")

    # Force RA / Dec to plain float degrees (handles masked, units, sexagesimal)
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

    # Drop rows where RA or Dec is NaN
    if "RA" in table.colnames and "Dec" in table.colnames:
        good = np.isfinite(table["RA"]) & np.isfinite(table["Dec"])
        table = table[good]

    table["catalog"] = catalog_tag
    if id_col and id_col in table.colnames:
        table["object_id"] = [str(r[id_col]) for r in table]
    else:
        table["object_id"] = [f"{catalog_tag}_{i}" for i in range(len(table))]
    return table


# ---------------------------------------------------------------------------
# Per-catalog fetchers
# ---------------------------------------------------------------------------

def _fetch_abell(row_limit: int, log) -> Table | None:
    log("Querying Abell cluster catalog (VizieR VII/110A)…")
    t = _vizier_query(
        "VII/110A",
        columns=["ACO", "_RA.icrs", "_DE.icrs", "z", "Rich", "Dclass"],
        row_limit=row_limit,
    )
    if t is None:
        log("WARNING: Could not retrieve Abell catalog.")
        return None
    t = _standardise(t, "_RA.icrs", "_DE.icrs", "Abell", "ACO")
    t["object_id"] = ["ACO_" + str(r["ACO"]) for r in t]
    return t


def _fetch_sdss(row_limit: int, log) -> Table | None:
    """
    SDSS is too large to fetch wholesale from VizieR — it returns a
    positional default slice instead of the full catalog.
    We tile the sky and query each tile via cone search instead.
    """
    log("Querying SDSS photometric catalog (VizieR II/294) via sky tiling…")
    v = Vizier(
        columns=["objID", "RA_ICRS", "DE_ICRS", "cl", "rmag"],
        row_limit=500,
    )
    ra_centres  = np.arange(0, 360, 15)
    dec_centres = np.arange(-80, 35, 10)
    n_tiles     = len(ra_centres) * len(dec_centres)
    log(f"  Querying {n_tiles} sky tiles…")

    all_tables = []
    queried    = 0
    for dec in dec_centres:
        for ra in ra_centres:
            centre = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
            try:
                result = v.query_region(centre, radius=8.0 * u.deg,
                                        catalog="II/294")
                if result and len(result) > 0:
                    all_tables.append(result[0])
            except Exception:
                pass
            queried += 1
            if queried % 30 == 0:
                log(f"  … {queried}/{n_tiles} tiles queried")

    if not all_tables:
        log("WARNING: No SDSS objects returned.")
        return None

    combined = vstack(all_tables)

    # Deduplicate by objID
    _, idx = np.unique(combined["objID"], return_index=True)
    combined = combined[idx]

    t = _standardise(combined, "RA_ICRS", "DE_ICRS", "SDSS", "objID")
    if "cl" in t.colnames:
        t = t[t["cl"] == 3]
    log(f"  Retrieved {len(t):,} SDSS galaxies after deduplication.")
    return t


def _fetch_2masx(row_limit: int, log) -> Table | None:
    log("Querying 2MASS Extended Source Catalog (VizieR VII/233)…")
    t = _vizier_query(
        "VII/233",
        columns=["_2MASX", "RAJ2000", "DEJ2000", "Ktmag"],
        row_limit=row_limit,
    )
    if t is None:
        log("WARNING: Could not retrieve 2MASX catalog.")
        return None
    return _standardise(t, "RAJ2000", "DEJ2000", "2MASX", "_2MASX")


def _fetch_ngc(row_limit: int, log) -> Table | None:
    log("Querying NGC/IC catalog (VizieR VII/118)…")
    t = _vizier_query(
        "VII/118",
        columns=["Name", "RAB2000", "DEB2000", "Type", "mag"],
        row_limit=row_limit,
    )
    if t is None:
        log("WARNING: Could not retrieve NGC catalog.")
        return None
    t = _standardise(t, "RAB2000", "DEB2000", "NGC", "Name")
    return t


def _fetch_ned(footprint, healpix_mask, healpix_nside, row_limit: int, log) -> Table | None:
    """
    Query NED.  For circular footprints (HLTDS, GBTDS) we query each field
    centre directly.  For sky-cut footprints (HLWAS) we tile the sky in a
    coarse RA/Dec grid, pre-filtering each tile against the footprint to keep
    memory use manageable.
    """
    log("Querying NED (NASA/IPAC Extragalactic Database)…")
    Ned.TIMEOUT = 60
    all_tables = []

    if footprint is not None and footprint["type"] == "circles":
        for field in footprint["fields"]:
            log(f"  NED cone search: {field['label']}")
            centre = SkyCoord(
                ra=field["ra"] * u.deg,
                dec=field["dec"] * u.deg,
                frame="icrs",
            )
            try:
                result = Ned.query_region(centre, radius=field["radius_deg"] * u.deg)
                if result is not None and len(result) > 0:
                    all_tables.append(result)
            except Exception as exc:
                log(f"  WARNING: NED query for {field['label']} failed: {exc}")

    else:
        # Tile the sky — 15° RA steps, 10° Dec steps
        ra_centres  = np.arange(0, 360, 15)
        dec_centres = np.arange(-80, 35, 10)
        n_tiles = len(ra_centres) * len(dec_centres)
        log(f"  Tiling sky with {n_tiles} NED tiles (15° × 10° grid)…")
        queried = 0
        for dec in dec_centres:
            for ra in ra_centres:
                centre = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
                try:
                    result = Ned.query_region(centre, radius=8.0 * u.deg)
                    if result is not None and len(result) > 0:
                        if footprint is not None:
                            for ra_col in ["RA(deg,icrs)", "RA"]:
                                if ra_col in result.colnames:
                                    break
                            for dec_col in ["DEC(deg,icrs)", "Dec"]:
                                if dec_col in result.colnames:
                                    break
                            mask = points_in_footprint(
                                result[ra_col].data.astype(float),
                                result[dec_col].data.astype(float),
                                footprint,
                                healpix_mask,
                                healpix_nside,
                            )
                            result = result[mask]
                        if len(result) > 0:
                            all_tables.append(result)
                except Exception:
                    pass
                queried += 1
                if queried % 20 == 0:
                    log(f"  … {queried}/{n_tiles} NED tiles queried")

    if not all_tables:
        log("WARNING: No NED results returned.")
        return None

    combined = vstack(all_tables)

    # Standardise RA/Dec column names
    for ra_col in ["RA(deg,icrs)", "RA", "ra"]:
        if ra_col in combined.colnames:
            if ra_col != "RA":
                combined.rename_column(ra_col, "RA")
            break
    for dec_col in ["DEC(deg,icrs)", "Dec", "dec"]:
        if dec_col in combined.colnames:
            if dec_col != "Dec":
                combined.rename_column(dec_col, "Dec")
            break

    combined["catalog"]   = "NED"
    if "Object Name" in combined.colnames:
        combined["object_id"] = combined["Object Name"]
    else:
        combined["object_id"] = [f"NED_{i}" for i in range(len(combined))]

    # Deduplicate
    _, idx = np.unique(combined["object_id"], return_index=True)
    return combined[idx]


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
