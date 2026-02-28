"""
roman_xmatch.pipeline
=====================
Core cross-match pipeline — shared by the CLI and the Streamlit GUI.

The single entry point run_pipeline() accepts a plain dataclass of options
so it can be called from either interface without modification.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from astropy.table import Table

from .footprints import get_footprint, SURVEY_KEYS
from .catalogs   import fetch_catalog, CATALOG_KEYS
from .crossmatch import load_healpix_mask, points_in_footprint
from .output     import write_outputs, ensure_required_columns


# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------

@dataclass
class PipelineOptions:
    surveys:         list[str]       = field(default_factory=lambda: ["hlwas"])
    catalogs:        list[str]       = field(default_factory=lambda: ["abell", "ngc"])
    mask_path:       Optional[str]   = None
    output_dir:      str             = "roman_xmatch_output"
    row_limit:       int             = 100_000
    custom_file:     Optional[str]   = None
    custom_ra_col:   str             = "RA"
    custom_dec_col:  str             = "Dec"


# ---------------------------------------------------------------------------
# Result dataclass — returned to caller (GUI can display this)
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    survey:       str
    catalog:      str
    n_retrieved:  int
    n_matched:    int
    fits_path:    str
    csv_path:     str
    error:        Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    opts: PipelineOptions,
    log: Callable[[str], None] = print,
) -> list[MatchResult]:
    """
    Run the cross-match pipeline.

    Parameters
    ----------
    opts : PipelineOptions
    log  : callable that receives progress messages (default: print)

    Returns
    -------
    results : list of MatchResult, one per (survey × catalog) combination
    """

    # Resolve "all" shorthand
    surveys  = SURVEY_KEYS                  if "all" in opts.surveys  else opts.surveys
    catalogs = [k for k in CATALOG_KEYS
                if k != "custom"]           if "all" in opts.catalogs else opts.catalogs

    # Include custom if a file was supplied and "custom" was requested
    if "custom" in opts.catalogs and opts.custom_file:
        if "custom" not in catalogs:
            catalogs.append("custom")

    # Validate
    for s in surveys:
        if s.lower() not in SURVEY_KEYS:
            raise ValueError(f"Unknown survey '{s}'. Choose from: {SURVEY_KEYS}")
    for c in catalogs:
        if c.lower() not in CATALOG_KEYS:
            raise ValueError(f"Unknown catalog '{c}'. Choose from: {CATALOG_KEYS}")

    # Load HEALPix mask if provided
    healpix_mask  = None
    healpix_nside = None
    if opts.mask_path:
        log(f"Loading HEALPix mask: {opts.mask_path}")
        healpix_mask, healpix_nside = load_healpix_mask(opts.mask_path)
        log(f"  nside={healpix_nside}, active pixels={np.sum(healpix_mask > 0):,}")

    results: list[MatchResult] = []

    for survey_key in surveys:
        footprint = get_footprint(survey_key)
        log(f"\n── {footprint['description']} ──")

        for cat_key in catalogs:
            log(f"\n[{survey_key.upper()} × {cat_key.upper()}]")

            # Fetch
            try:
                table = fetch_catalog(
                    cat_key,
                    row_limit        = opts.row_limit,
                    footprint        = footprint,
                    healpix_mask     = healpix_mask,
                    healpix_nside    = healpix_nside,
                    custom_file      = opts.custom_file,
                    custom_ra_col    = opts.custom_ra_col,
                    custom_dec_col   = opts.custom_dec_col,
                    progress_callback= log,
                )
            except Exception as exc:
                log(f"  ERROR fetching {cat_key}: {exc}")
                results.append(MatchResult(
                    survey=survey_key, catalog=cat_key,
                    n_retrieved=0, n_matched=0,
                    fits_path="", csv_path="",
                    error=str(exc),
                ))
                continue

            if table is None or len(table) == 0:
                log("  No objects retrieved.")
                results.append(MatchResult(
                    survey=survey_key, catalog=cat_key,
                    n_retrieved=0, n_matched=0,
                    fits_path="", csv_path="",
                ))
                continue

            n_retrieved = len(table)
            log(f"  Retrieved {n_retrieved:,} objects.")

            # Footprint filter (NED pre-filters during tiling)
            if cat_key != "ned":
                try:
                    ra_vals  = np.array(table["RA"],  dtype=float)
                    dec_vals = np.array(table["Dec"], dtype=float)
                    inside = points_in_footprint(
                        ra_vals, dec_vals,
                        footprint,
                        healpix_mask,
                        healpix_nside,
                    )
                    table = table[inside]
                except Exception as exc:
                    log(f"  ERROR during footprint test: {exc}")
                    results.append(MatchResult(
                        survey=survey_key, catalog=cat_key,
                        n_retrieved=n_retrieved, n_matched=0,
                        fits_path="", csv_path="",
                        error=str(exc),
                    ))
                    continue

            n_matched = len(table)
            log(f"  Matched within {footprint['name']}: {n_matched:,}")

            if n_matched == 0:
                results.append(MatchResult(
                    survey=survey_key, catalog=cat_key,
                    n_retrieved=n_retrieved, n_matched=0,
                    fits_path="", csv_path="",
                ))
                continue

            table = ensure_required_columns(table, cat_key)

            fits_path, csv_path = write_outputs(
                table,
                survey_name  = footprint["name"],
                catalog_name = cat_key,
                output_dir   = opts.output_dir,
                log          = log,
            )

            results.append(MatchResult(
                survey=survey_key, catalog=cat_key,
                n_retrieved=n_retrieved, n_matched=n_matched,
                fits_path=fits_path, csv_path=csv_path,
            ))

    # Summary
    total = sum(r.n_matched for r in results)
    log(f"\n{'='*55}")
    log(f"  Complete — {total:,} total matched objects")
    log(f"  Output directory: {os.path.abspath(opts.output_dir)}")
    log(f"{'='*55}")

    return results
