"""
roman_xmatch.output
===================
Write cross-match results to FITS and CSV files.
"""

import os
import numpy as np
from astropy.table import Table


def write_outputs(
    table: Table,
    survey_name: str,
    catalog_name: str,
    output_dir: str = ".",
    log=None,
) -> tuple[str, str]:
    """
    Write a matched-objects Table to both FITS and CSV.

    Parameters
    ----------
    table        : astropy Table of matched objects
    survey_name  : e.g. "HLWAS"
    catalog_name : e.g. "abell"
    output_dir   : directory for output files
    log          : optional callable(message) for status feedback

    Returns
    -------
    (fits_path, csv_path) — absolute paths of files written (empty string if failed)
    """
    def _log(msg):
        if log:
            log(msg)

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.join(
        output_dir,
        f"{survey_name.upper()}_{catalog_name.lower()}_matches",
    )

    # ---- FITS ------------------------------------------------------------
    fits_path = base + ".fits"
    try:
        table.write(fits_path, format="fits", overwrite=True)
        _log(f"Saved FITS : {os.path.abspath(fits_path)}")
    except Exception as exc:
        _log(f"WARNING: Could not write FITS: {exc}")
        fits_path = ""

    # ---- CSV -------------------------------------------------------------
    csv_path = base + ".csv"
    try:
        df = table.to_pandas()
        # Decode any byte-string columns to regular str
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    df[col] = df[col].str.decode("utf-8")
                except Exception:
                    pass
        df.to_csv(csv_path, index=False)
        _log(f"Saved CSV  : {os.path.abspath(csv_path)}")
    except Exception as exc:
        _log(f"WARNING: Could not write CSV: {exc}")
        csv_path = ""

    return fits_path, csv_path


def ensure_required_columns(table: Table, catalog_tag: str) -> Table:
    """
    Make sure RA, Dec, catalog, and object_id columns are present.
    Fills missing ones with sensible defaults so writers never crash.
    """
    defaults = {
        "RA":        np.nan,
        "Dec":       np.nan,
        "catalog":   catalog_tag.upper(),
        "object_id": "",
    }
    for col, default in defaults.items():
        if col not in table.colnames:
            table[col] = default
    return table
