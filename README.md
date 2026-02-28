# 🔭 roman-xmatch

**Cross-correlate Nancy Grace Roman Space Telescope survey footprints with major astronomical catalogs.**

Given a Roman survey footprint (built-in approximations or your own HEALPix mask), `roman-xmatch` queries remote catalog services, tests which objects fall within the footprint, and saves the results as both **FITS** and **CSV** files.

---

## Supported surveys

| Key | Survey | Area |
|-----|--------|------|
| `HLWAS` | High Latitude Wide Area Survey | ~5,000 deg² |
| `HLTDS` | High Latitude Time Domain Survey | ~18 deg² (2 fields) |
| `GBTDS` | Galactic Bulge Time Domain Survey | ~2 deg² (6 pointings) |

Footprints are approximated from the **ROTAC Final Report (April 2025)**.  
When NASA/IPAC publish official HEALPix mask files, you can supply them via `--mask`.

## Supported catalogs

| Key | Source |
|-----|--------|
| `abell` | Abell clusters of galaxies — VizieR VII/110A |
| `sdss` | SDSS photometric catalog DR7 — VizieR II/294 |
| `2masx` | 2MASS Extended Source Catalog — VizieR VII/233 |
| `ngc` | NGC/IC catalog — VizieR VII/118 |
| `ned` | NASA/IPAC Extragalactic Database |
| `custom` | Your own FITS or CSV file |

---

## Installation

### For end users — `pipx` (recommended)

`pipx` installs the tool in its own isolated Python environment so it never
conflicts with anything else on your system.

**Step 1 — install pipx** (skip if you already have it)

```bash
# macOS
brew install pipx
pipx ensurepath

# Linux / WSL
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Windows (PowerShell)
python -m pip install --user pipx
python -m pipx ensurepath
```

**Step 2 — install roman-xmatch**

```bash
pipx install roman-xmatch
```

That's it.  The `roman-xmatch` command is now available system-wide.

> **HEALPix support** (optional — needed only for custom mask files):
> ```bash
> pipx inject roman-xmatch healpy
> ```

---

### For developers — editable install

```bash
git clone https://github.com/YOUR_USERNAME/roman-xmatch.git
cd roman-xmatch
pip install -e ".[dev]"
```

---

## Usage

### GUI (browser — recommended for non-programmers)

```bash
roman-xmatch
```

This opens a browser window with a point-and-click interface.  You can:
- Select a survey and catalogs from drop-down menus
- Upload a HEALPix mask file or your own custom catalog
- Watch live progress as the cross-match runs
- Download results as FITS or CSV directly from the browser

### CLI (headless — for scripts and automation)

```bash
# HLWAS footprint vs Abell clusters and NGC (default)
roman-xmatch --cli --survey HLWAS --catalogs abell ngc

# All surveys vs all catalogs
roman-xmatch --cli --survey all --catalogs all

# HLTDS with a real HEALPix mask
roman-xmatch --cli --survey HLTDS --mask roman_hltds.fits --catalogs abell 2masx

# Include your own source list
roman-xmatch --cli --survey HLWAS --catalogs custom --custom-file my_sources.csv

# Quick test (small row limit)
roman-xmatch --cli --survey GBTDS --catalogs abell ngc --row-limit 5000
```

Full CLI reference:

```
roman-xmatch --cli [options]

  --survey   -s   HLWAS | HLTDS | GBTDS | all         (default: hlwas)
  --catalogs -c   abell sdss 2masx ngc ned custom all  (default: abell ngc)
  --mask     -m   Path to HEALPix FITS mask file
  --output-dir -o Output directory                     (default: roman_xmatch_output/)
  --row-limit  -r Max rows per catalog query           (default: 100000)
  --custom-file   Path to custom catalog (FITS or CSV)
  --custom-ra-col   RA column name in custom file      (default: RA)
  --custom-dec-col  Dec column name in custom file     (default: Dec)
```

### Python API

```python
from roman_xmatch.pipeline import PipelineOptions, run_pipeline

opts = PipelineOptions(
    surveys    = ["hlwas"],
    catalogs   = ["abell", "ngc"],
    output_dir = "my_results",
    row_limit  = 50_000,
)

results = run_pipeline(opts)

for r in results:
    print(f"{r.survey} × {r.catalog}: {r.n_matched} matches → {r.csv_path}")
```

---

## Outputs

Results are saved to the output directory, one file pair per survey × catalog:

```
roman_xmatch_output/
├── HLWAS_abell_matches.fits
├── HLWAS_abell_matches.csv
├── HLWAS_ngc_matches.fits
├── HLWAS_ngc_matches.csv
└── ...
```

Each file contains all original catalog columns plus:

| Column | Description |
|--------|-------------|
| `RA` | Right Ascension (degrees, J2000) |
| `Dec` | Declination (degrees, J2000) |
| `catalog` | Source catalog name |
| `object_id` | Object identifier |

---

## Updating

```bash
pipx upgrade roman-xmatch
```

---

## Notes on footprint accuracy

Roman has not yet launched (planned late 2026).  The built-in footprints are
**approximations** based on the April 2025 ROTAC report:

- **HLWAS** uses Galactic latitude (|b| > 20°), Ecliptic latitude (|β| > 15°),
  and a declination ceiling (Dec < +30°) to mimic the sky coverage.  The actual
  boundary will be more irregular.
- **HLTDS** uses the two confirmed field centres (ELAIS-N1 and EDFS) as circular
  caps of radius 2.4°.
- **GBTDS** uses the six WFI pointing centres from the report as 0.3° circles.

When NASA/IPAC publish official HEALPix mask files, pass them with `--mask` or
upload them in the GUI to get exact footprints.

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

## Citation

If you use this tool in published work, please cite the ROTAC Final Report:

> Roman Observatory Time Allocation Committee (ROTAC), 2025.
> *Roman Core Community Survey Recommendations.*
> https://roman.gsfc.nasa.gov/science/ccs/ROTAC-Report-20250424-v1.pdf

and the relevant catalog papers for whichever catalogs you use.
