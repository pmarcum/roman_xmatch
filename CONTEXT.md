# roman-xmatch — Developer Context

This file captures architecture decisions, design rationale, and implementation
details to help resume development in a future session.

---

## Repository layout

```
roman_xmatch/
├── __init__.py
├── cache.py          — loads .fits.gz files from roman_xmatch/data/
├── catalogs.py       — bundled catalog loaders, CATALOG_KEYS, CATALOG_LABELS
├── cli.py            — command-line entry point (roman-xmatch --cli)
├── crossmatch.py     — points_in_footprint(), HEALPix mask support
├── footprints.py     — get_footprint(), SURVEY_KEYS, footprint geometry
├── gui.py            — Tkinter desktop GUI, all widget layout
├── output.py         — write_outputs() writes FITS + CSV pairs
├── pipeline.py       — PipelineOptions dataclass, run_pipeline(), _and_match()
├── plotting.py       — interactive Tkinter/matplotlib sky plot
└── data/
    ├── abell.fits.gz         (~33 KB,  ~2,700 Abell clusters)
    ├── mcxc.fits.gz          (~28 KB,  ~1,700 MCXC X-ray clusters)
    ├── ngc_ugc.fits.gz       (~328 KB, ~26,000 NGC/IC + UGC galaxies)
    ├── xray_gal.fits.gz      (~523 KB, ~23,500 X-ray galaxies)
    ├── 2masx.fits.gz         (~33 MB,  ~1.6M 2MASS extended sources)
    └── sdss.fits.gz          (~96 MB,  ~3-4M SDSS DR18 spectroscopic galaxies)
```

---

## Architecture: bundled catalogs

All catalogs are **pre-built** and ship with the package — no network access
required at runtime. Catalogs are stored as gzip-compressed FITS files in
`roman_xmatch/data/`. The `cache.py` module loads them via `load_bundled(key)`.

Catalogs were built once by `scripts/build_catalogs.py` (maintainer-only,
not distributed). Each catalog has at minimum these columns:
`RA`, `Dec`, `catalog`, `object_id`.

**SDSS note:** Uses spectroscopic galaxies only (`s.class = 'GALAXY'` from
SpecObj × PhotoObj join). This avoids the ~100-200M photometric catalog which
has massive star contamination near the Galactic plane.

---

## Pipeline (pipeline.py)

### PipelineOptions fields
```python
surveys:                list[str]   # e.g. ["hlwas"]
catalogs:               list[str]   # e.g. ["ngc_ugc", "xray_gal"]
mask_path:              str|None    # HEALPix FITS mask file
output_dir:             str         # default "roman_xmatch_output"
row_limit:              int         # default 100_000
custom_file:            str|None    # user-supplied FITS or CSV
custom_ra_col:          str         # default "RA"
custom_dec_col:         str         # default "Dec"
plot_callback:          callable    # called with (png_path, survey_key)
match_mode:             str         # "OR" (default) or "AND"
match_tolerance_arcsec: float       # default 5.0
```

### OR mode
Each catalog fetched and footprint-filtered independently. One output file
pair (FITS + CSV) per catalog. Original behaviour.

### AND mode
All catalogs fetched and footprint-filtered individually first. Then
`_and_match()` does N-way positional cross-match anchored to the FIRST
catalog in selection order. Only sources with a counterpart in ALL other
catalogs within `match_tolerance_arcsec` survive. Single output file named
e.g. `HLWAS_ngc_ugc_AND_xray_gal_matches.csv` with extra columns:
`matched_<cat>_id`, `matched_<cat>_sep_arcsec`.

In AND mode, a single `MatchResult` is emitted using the anchor catalog key
so the plot loads the file once and labels with the anchor's formatter.

### MatchResult fields
```python
survey, catalog, n_retrieved, n_matched, fits_path, csv_path, error
```

---

## GUI (gui.py)

Tkinter desktop window, opened by `roman-xmatch` with no arguments.

### Key widgets and variables
- `survey_var` — StringVar for survey dropdown
- `cat_vars` — dict {cat_key: BooleanVar} for catalog checkboxes
- `match_mode_var` — StringVar, "OR" or "AND"
- `tol_var` — StringVar, tolerance in arcsec (enabled only in AND mode)
- `mask_path_var` — StringVar for HEALPix mask file path
- `custom_path_var` — StringVar for custom catalog file path
- `last_plot` — dict with keys: path, survey_key, results, catalog_order, tolerance_arcsec

### Tooltips
ToolTip class (defined at top of gui.py) shows on hover with 500ms delay.
Tooltips on: Survey label, Catalogs label, Catalog match label,
HEALPix mask label, Custom file label.

### Threading
Pipeline runs in background thread via `run_task()` to keep UI responsive.
`on_plot_ready(png_path, survey_key)` callback enables the View Sky Plot button.
`on_run_complete(results)` stores results and catalog_order in `last_plot`.

### Default window size
780×820, minsize 780×820.

---

## Interactive sky plot (plotting.py)

### Key constants
```python
CATALOG_COLORS  — dict {cat_key: hex_color}
CATALOG_MARKERS — dict {cat_key: matplotlib_marker}
    # abell='^', chandra-clusters='D', sdss='.', 2masx='s', ngc_ugc='o',
    # xray_gal='+', custom='*'
LABEL_ZOOM_THRESHOLD — dict {cat_key: degrees_view_width}
MAX_LABELS = 80
```

### Symbol rendering
- Filled markers (o, s, ^, D): alpha=0.45, no edge, semi-transparent
- Line markers (+, x): alpha=0.7, linewidth=2.0, c=color (not "none" — 
  setting c="none" with alpha makes them invisible)
- Size: `max(25, min(150, 200000 / max(n, 1)))`

### _load_catalog_data()
Returns `{cat_key: (ra, dec, ids, suppress)}` where `suppress` is a boolean
array. Dots are always plotted at true positions. `suppress[i]=True` means
source i's label is suppressed because a higher-priority catalog source is
within `tolerance_arcsec`. Priority = catalog_order from GUI selection.

### scatter_artists dict
`{cat_key: (ra_w, dec, ids, sc, suppress)}` — ra_w is RA wrapped to [-180,180]
for display. Used by _LabelManager and _export_view.

### Mouse controls
- Scroll up/down: zoom in/out centred on cursor
- Left or right click drag: pan
- No toolbar zoom/pan tools (removed to avoid conflicts)

### Toolbar buttons (single row, bottom)
1. Labels: OFF/ON — toggle object labels (green when ON)
2. Save Figure… — saves PNG/PDF/SVG of current view
3. Save Objects in View… — exports visible objects to CSV with
   filename encoding current RA/Dec bounds

### Coordinate display
Custom `ax.format_coord` shows:
`RA 14:23:19.6  Dec +34:48:40    (215.8312°,  +34.8111°)`
Displayed in a tk.Label on the right side of the button bar,
updated via `canvas.mpl_connect("motion_notify_event", ...)`.

### Label formatting (_format_label)
- abell:            "ACO_426"       → "426"
- chandra-clusters: "MCXC_J0000.1"  → "0000.1+0816"
- ngc_ugc:          "NGC_7801"      → "N7801", "NGC_I5370" → "I5370", "UGC_891" → "U891"
- xray_gal:         "4XMM_J123..."  → "123456.7+..." (9 chars)
- 2masx:            "2MASX J123..." → "12345678..." (9 chars)
- sdss:             objID           → "215.5+12.3" (RA+Dec to 1 decimal)

---

## Catalog keys reference

| Key | Label | File |
|-----|-------|------|
| abell | Abell Clusters | abell.fits.gz |
| chandra-clusters | Chandra Galaxy Clusters — MCXC | mcxc.fits.gz |
| sdss | SDSS DR18 Spectroscopic Galaxies | sdss.fits.gz |
| 2masx | 2MASS Extended Source Catalog | 2masx.fits.gz |
| ngc_ugc | NGC/IC + UGC Galaxies | ngc_ugc.fits.gz |
| xray_gal | X-ray Galaxies — Chandra CSC 2.1 + XMM 4XMM-DR13 | xray_gal.fits.gz |
| custom | User-supplied FITS or CSV | (runtime) |

---

## Known issues / future work

- `xray_gal.fits.gz` is smaller than expected (~23,500 sources) because
  Route B (CXC TAP → NGC/UGC match) and Route C (XMM → NGC/UGC match)
  largely duplicate Route A (CSC × SDSS) sources after deduplication.
  The catalog is probably close to complete for unique X-ray galaxies.

- SDSS `sdss.fits.gz` at 96 MB is close to GitHub's 100 MB per-file limit.
  It is tracked via Git LFS. If it causes issues, consider hosting on
  GitHub Releases and downloading on first use via cache.py.

- The `tests/test_basic.py` smoke tests cover footprint geometry only.
  No tests for catalog loading, pipeline, or GUI yet.

---

## Git / deployment

- Repo: https://github.com/pmarcum/roman_xmatch
- Default branch: master
- Large files (.fits.gz) tracked via Git LFS
- Install: `pipx install git+https://github.com/pmarcum/roman_xmatch.git`
- Update alias: `romanupdate` (defined in ~/.bashrc)
  = git add . && git commit && git push origin master && pipx install --force -e .
