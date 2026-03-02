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
    plot_callback:          Optional[Callable[[str, str], None]] = None
    # plot_callback(png_path, survey_key) — called after each survey's plot is saved
    match_mode:             str   = "OR"   # "OR" = union, "AND" = intersection
    match_tolerance_arcsec: float = 5.0    # positional tolerance for AND mode


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

# ---------------------------------------------------------------------------
# AND-mode cross-match
# ---------------------------------------------------------------------------

def _and_match(
    tables: dict,           # {cat_key: Table} — already footprint-filtered
    tolerance_arcsec: float,
    log,
) -> Table:
    """
    N-way positional cross-match in AND mode.

    Anchors to the first catalog in `tables` (preserves selection order).
    For each source in the anchor, finds the nearest neighbour in every other
    catalog within `tolerance_arcsec`.  Only sources with a match in ALL
    other catalogs are kept.

    Returns a single Table with columns:
        RA, Dec, catalog, object_id,
        matched_<cat>_id, matched_<cat>_sep_arcsec   (for each non-anchor cat)
    """
    cat_keys = list(tables.keys())
    anchor_key = cat_keys[0]
    other_keys = cat_keys[1:]
    anchor = tables[anchor_key]

    tol_rad = np.radians(tolerance_arcsec / 3600.0)

    anchor_ra  = np.radians(np.array(anchor["RA"],  dtype=float))
    anchor_dec = np.radians(np.array(anchor["Dec"], dtype=float))
    n_anchor   = len(anchor)

    # For each other catalog, find nearest neighbour to each anchor source
    # keep[i] = True if source i has a match in ALL other catalogs
    keep        = np.ones(n_anchor, dtype=bool)
    match_ids   = {k: np.full(n_anchor, "", dtype=object)   for k in other_keys}
    match_seps  = {k: np.full(n_anchor, np.nan)             for k in other_keys}

    for other_key in other_keys:
        other = tables[other_key]
        if len(other) == 0:
            log(f"    {other_key.upper()}: 0 sources — no AND matches possible.")
            keep[:] = False
            break

        other_ra  = np.radians(np.array(other["RA"],        dtype=float))
        other_dec = np.radians(np.array(other["Dec"],       dtype=float))
        other_ids = np.array(other["object_id"]).astype(str)

        log(f"    Matching {anchor_key.upper()} ({n_anchor:,}) → "
            f"{other_key.upper()} ({len(other):,})…")

        # Vectorised haversine: for each anchor source find closest other source
        # Process in chunks to avoid huge memory allocation
        CHUNK = 5_000
        for start in range(0, n_anchor, CHUNK):
            end  = min(start + CHUNK, n_anchor)
            a_ra  = anchor_ra [start:end, np.newaxis]   # (chunk, 1)
            a_dec = anchor_dec[start:end, np.newaxis]
            dra   = other_ra  - a_ra                    # (chunk, N_other)
            ddec  = other_dec - a_dec
            hav   = (np.sin(ddec / 2) ** 2 +
                     np.cos(a_dec) * np.cos(other_dec) * np.sin(dra / 2) ** 2)
            sep   = 2 * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))  # radians
            best  = np.argmin(sep, axis=1)
            best_sep = sep[np.arange(end - start), best]

            matched = best_sep <= tol_rad
            # Mark anchor sources with no match
            no_match = ~matched
            keep[start:end][no_match] = False
            # Store match info for those that do match
            match_ids [other_key][start:end][matched] = other_ids[best[matched]]
            match_seps[other_key][start:end][matched] = (
                np.degrees(best_sep[matched]) * 3600.0
            )

        n_surviving = int(keep.sum())
        log(f"      {n_surviving:,} anchor sources matched within "
            f"{tolerance_arcsec:.1f} arcsec.")

    # Build output table from surviving anchor rows
    out = Table()
    out["RA"]        = np.array(anchor["RA"],        dtype=float)[keep]
    out["Dec"]       = np.array(anchor["Dec"],       dtype=float)[keep]
    out["catalog"]   = np.array(anchor["catalog"]  )[keep] if "catalog"   in anchor.colnames else anchor_key
    out["object_id"] = np.array(anchor["object_id"]).astype(str)[keep]

    # Carry through any extra anchor columns (e.g. z, zErr for SDSS)
    skip = {"RA", "Dec", "catalog", "object_id"}
    for col in anchor.colnames:
        if col not in skip:
            out[col] = np.array(anchor[col])[keep]

    # Add match columns for each other catalog — force uniform string dtype for FITS
    for other_key in other_keys:
        safe = other_key.replace("-", "_")
        ids_col = np.array(match_ids[other_key][keep], dtype=str)  # uniform dtype
        out[f"matched_{safe}_id"]         = ids_col
        out[f"matched_{safe}_sep_arcsec"] = match_seps[other_key][keep].astype(float)

    return out


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

        # ── Fetch and footprint-filter each catalog ────────────────────────
        fetched = {}   # cat_key -> (table, n_retrieved)  for all successful fetches

        for cat_key in catalogs:
            log(f"\n[{survey_key.upper()} × {cat_key.upper()}]")

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

            # Footprint filter
            if cat_key != "ned":
                try:
                    for wrong, right in [("ra","RA"),("dec","Dec"),("DEC","Dec")]:
                        if wrong in table.colnames and right not in table.colnames:
                            table.rename_column(wrong, right)
                    if "RA" not in table.colnames or "Dec" not in table.colnames:
                        raise KeyError(
                            f"Expected 'RA'/'Dec' columns, got: {table.colnames}"
                        )
                    ra_vals  = np.array(table["RA"],  dtype=float)
                    dec_vals = np.array(table["Dec"], dtype=float)
                    inside   = points_in_footprint(
                        ra_vals, dec_vals, footprint,
                        healpix_mask, healpix_nside,
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

            n_in_footprint = len(table)
            log(f"  Matched within {footprint['name']}: {n_in_footprint:,}")

            if n_in_footprint == 0:
                results.append(MatchResult(
                    survey=survey_key, catalog=cat_key,
                    n_retrieved=n_retrieved, n_matched=0,
                    fits_path="", csv_path="",
                ))
                continue

            table = ensure_required_columns(table, cat_key)
            fetched[cat_key] = (table, n_retrieved)

        # ── OR mode: write each catalog independently (original behaviour) ──
        if opts.match_mode.upper() == "OR" or len(fetched) <= 1:
            for cat_key, (table, n_retrieved) in fetched.items():
                fits_path, csv_path = write_outputs(
                    table,
                    survey_name  = footprint["name"],
                    catalog_name = cat_key,
                    output_dir   = opts.output_dir,
                    log          = log,
                )
                results.append(MatchResult(
                    survey=survey_key, catalog=cat_key,
                    n_retrieved=n_retrieved, n_matched=len(table),
                    fits_path=fits_path, csv_path=csv_path,
                ))

        # ── AND mode: positional intersection across all catalogs ──────────
        else:
            log(f"\n[AND MODE — tolerance {opts.match_tolerance_arcsec:.1f} arcsec]")
            tables_only = {k: t for k, (t, _) in fetched.items()}
            try:
                and_table = _and_match(
                    tables_only,
                    tolerance_arcsec = opts.match_tolerance_arcsec,
                    log = log,
                )
            except Exception as exc:
                log(f"  ERROR during AND cross-match: {exc}")
                and_table = None

            if and_table is not None and len(and_table) > 0:
                anchor_key  = list(fetched.keys())[0]
                other_keys  = list(fetched.keys())[1:]
                catalog_name = anchor_key + "_AND_" + "_".join(other_keys)
                fits_path, csv_path = write_outputs(
                    and_table,
                    survey_name  = footprint["name"],
                    catalog_name = catalog_name,
                    output_dir   = opts.output_dir,
                    log          = log,
                )
                log(f"  AND result: {len(and_table):,} sources in all catalogs.")
                # Report one MatchResult per catalog for the summary
                for cat_key, (table, n_retrieved) in fetched.items():
                    results.append(MatchResult(
                        survey=survey_key, catalog=cat_key,
                        n_retrieved=n_retrieved, n_matched=len(and_table),
                        fits_path=fits_path, csv_path=csv_path,
                    ))
            else:
                log("  AND result: 0 sources matched across all catalogs.")
                for cat_key, (table, n_retrieved) in fetched.items():
                    results.append(MatchResult(
                        survey=survey_key, catalog=cat_key,
                        n_retrieved=n_retrieved, n_matched=0,
                        fits_path="", csv_path="",
                    ))

    # Summary
    total = sum(r.n_matched for r in results)

    # Generate sky plot per survey
    for survey_key in surveys:
        survey_results = [r for r in results if r.survey.lower() == survey_key.lower()]
        if any(r.n_matched > 0 for r in survey_results):
            try:
                from .plotting import make_sky_plot
                log(f"\n  Generating sky plot for {survey_key.upper()}…")
                png_path = make_sky_plot(
                    results    = survey_results,
                    survey_key = survey_key,
                    output_dir = opts.output_dir,
                    healpix_mask  = healpix_mask,
                    healpix_nside = healpix_nside,
                )
                if png_path and opts.plot_callback:
                    opts.plot_callback(png_path, survey_key)
            except Exception as exc:
                log(f"  [plot] Warning: could not generate sky plot: {exc}")

    log(f"\n{'='*55}")
    log(f"  Complete — {total:,} total matched objects")
    log(f"  Output directory: {os.path.abspath(opts.output_dir)}")
    log(f"{'='*55}")

    return results
