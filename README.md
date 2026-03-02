# 🔭 roman-xmatch

**Cross-match Nancy Grace Roman Space Telescope survey footprints with major astronomical catalogs.**

Given a Roman survey footprint (built-in approximations or your own HEALPix mask),
`roman-xmatch` identifies which objects from pre-bundled catalogs fall within the
footprint and saves the results as both **FITS** and **CSV** files.  An interactive
sky plot lets you explore, zoom, pan, and export what you find.

---

## Supported surveys

| Key | Survey | Area |
|-----|--------|------|
| `hlwas` | High Latitude Wide Area Survey | ~5,000 deg² |
| `hltds` | High Latitude Time Domain Survey | ~18 deg² (2 fields) |
| `gbtds` | Galactic Bulge Time Domain Survey | ~2 deg² (6 pointings) |

Footprints are approximated from the **ROTAC Final Report (April 2025)**.
When NASA/IPAC publish official HEALPix mask files you can supply them via
the HEALPix Mask option to get exact footprints.

---

## Bundled catalogs

All catalogs are pre-built and ship with the package — no network access required
at run time.

| Key | Catalog | Source | Objects |
|-----|---------|--------|---------|
| `abell` | Abell Clusters | VizieR VII/110A | ~2,700 |
| `chandra-clusters` | X-ray Galaxy Clusters (MCXC) | VizieR J/A+A/534/A109 | ~1,700 |
| `ngc_ugc` | NGC/IC + UGC Galaxies | VizieR VII/118 + VII/26D | ~26,000 |
| `xray_gal` | X-ray Galaxies (Chandra CSC 2.1 + XMM 4XMM-DR13) | CXC + VizieR IX/69 | ~23,500 |
| `2masx` | 2MASS Extended Source Catalog | VizieR VII/233 | ~1.6M |
| `sdss` | SDSS DR18 Spectroscopic Galaxies | SkyServer | ~3–4M |
| `custom` | Your own FITS or CSV file | — | — |

---

## Installation

### For end users — `pipx` (recommended)

`pipx` installs the tool in its own isolated Python environment so it never
conflicts with anything else on your system.

**Step 1 — install pipx** (skip if you already have it)

```bash
# macOS
brew install pipx && pipx ensurepath

# Linux / WSL
python3 -m pip install --user pipx && python3 -m pipx ensurepath

# Windows (PowerShell)
python -m pip install --user pipx && python -m pipx ensurepath
```

> **Windows users:** Install Python from [python.org](https://python.org) rather than
> the Microsoft Store to ensure tkinter is available (required for the GUI).
> WSL2 is not required but is a reliable alternative if you encounter any issues.

**Step 2 — install roman-xmatch**

```bash
pipx install git+https://github.com/pmarcum/roman_xmatch.git
```

That's it. The `roman-xmatch` command is now available system-wide.

> **HEALPix support** (optional — needed only for custom mask files):
> ```bash
> pipx inject roman-xmatch healpy
> ```

**To update to the latest version:**
```bash
pipx reinstall roman-xmatch
```

---

### For developers — editable install

```bash
git clone https://github.com/pmarcum/roman_xmatch.git
cd roman_xmatch
pip install -e ".[dev]"
```

---

## Usage

### GUI (recommended)

```bash
roman-xmatch
```

Opens a desktop window with a point-and-click interface:

- Select a **survey** footprint from the drop-down
- Check one or more **catalogs** to search
- Choose **OR** mode (union — all matching objects from each catalog) or
  **AND** mode (intersection — only objects appearing in *all* selected
  catalogs within a user-specified positional tolerance)
- Optionally supply a **HEALPix mask** file for a custom footprint
- Optionally supply a **custom catalog** (FITS or CSV)
- Click **Run Cross-Match** and watch live progress
- Click **View Sky Plot** to open an interactive sky map where you can:
  - Scroll to zoom in/out centred on the cursor
  - Click and drag (left or right button) to pan
  - Toggle object labels on/off
  - Save the current figure view as PNG/PDF/SVG
  - Export the objects visible in the current view to CSV

### CLI (headless — for scripts and automation)

```bash
# HLWAS footprint vs NGC/UGC galaxies and Abell clusters
roman-xmatch --cli --survey hlwas --catalogs ngc_ugc abell

# All surveys vs all catalogs
roman-xmatch --cli --survey all --catalogs all

# HLTDS with a custom HEALPix mask
roman-xmatch --cli --survey hltds --mask roman_hltds.fits --catalogs abell 2masx

# AND mode: only sources appearing in both catalogs within 5 arcsec
roman-xmatch --cli --survey hlwas --catalogs ngc_ugc xray_gal --match-mode AND --tolerance 5.0

# Include your own source list
roman-xmatch --cli --survey hlwas --catalogs custom --custom-file my_sources.csv
```

Full CLI reference:

```
roman-xmatch --cli [options]

  --survey   -s   hlwas | hltds | gbtds | all              (default: hlwas)
  --catalogs -c   abell chandra-clusters sdss 2masx         (default: ngc_ugc)
                  ngc_ugc xray_gal custom all
  --match-mode    OR | AND                                  (default: OR)
  --tolerance     Positional tolerance in arcsec for AND    (default: 5.0)
  --mask     -m   Path to HEALPix FITS mask file
  --output-dir -o Output directory                          (default: roman_xmatch_output/)
  --row-limit  -r Max rows per catalog query                (default: 100000)
  --custom-file   Path to custom catalog (FITS or CSV)
  --custom-ra-col   RA column name in custom file           (default: RA)
  --custom-dec-col  Dec column name in custom file          (default: Dec)
```

### Python API

```python
from roman_xmatch.pipeline import PipelineOptions, run_pipeline

opts = PipelineOptions(
    surveys                = ["hlwas"],
    catalogs               = ["ngc_ugc", "xray_gal"],
    match_mode             = "AND",      # OR (default) or AND
    match_tolerance_arcsec = 5.0,
    output_dir             = "my_results",
)

results = run_pipeline(opts)

for r in results:
    print(f"{r.survey} × {r.catalog}: {r.n_matched} matches → {r.csv_path}")
```

---

## Outputs

Results are saved to the output directory, one file pair per survey × catalog
(OR mode) or one combined file (AND mode):

```
roman_xmatch_output/
├── HLWAS_ngc_ugc_matches.fits
├── HLWAS_ngc_ugc_matches.csv
├── HLWAS_xray_gal_matches.fits
├── HLWAS_xray_gal_matches.csv
└── HLWAS_sky_plot.png
```

In **AND mode**, a single output file is produced named e.g.
`HLWAS_ngc_ugc_AND_xray_gal_matches.csv`, with extra columns
`matched_<catalog>_id` and `matched_<catalog>_sep_arcsec` for each
additional catalog.

Each file contains at minimum:

| Column | Description |
|--------|-------------|
| `RA` | Right Ascension (degrees, J2000) |
| `Dec` | Declination (degrees, J2000) |
| `catalog` | Source catalog name |
| `object_id` | Object identifier |

---

## Notes on footprint accuracy

Roman has not yet launched (planned late 2026). The built-in footprints are
**approximations** based on the April 2025 ROTAC report:

- **HLWAS** uses Galactic latitude (|b| > 20°), Ecliptic latitude (|β| > 15°),
  and a declination ceiling (Dec < +30°) to approximate the sky coverage.
  The actual boundary will be more irregular.
- **HLTDS** uses the two confirmed field centres (ELAIS-N1 and EDFS) as
  circular caps of radius 2.4°.
- **GBTDS** uses the six WFI pointing centres from the report as 0.3° circles.

Supply a `--mask` HEALPix file for exact footprints once NASA/IPAC publish them.

---

## Development

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=roman_xmatch

# Lint
ruff check roman_xmatch/
```

---

## License

MIT — see [LICENSE](LICENSE).

---

## Citation

If you use this tool in published work, please cite the ROTAC Final Report:

> Roman Observatory Time Allocation Committee (ROTAC), 2025.
> *Roman Core Community Survey Recommendations.*
> https://roman.gsfc.nasa.gov/science/ccs/ROTAC-Report-20250424-v1.pdf

and the relevant catalog papers for whichever catalogs you use.
