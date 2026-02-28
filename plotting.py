"""
roman_xmatch.plotting
=====================
Sky plots of matched sources overlaid on the Roman survey footprint.

Produces an equatorial (RA/Dec) scatter plot with:
  - Survey footprint shown as a shaded background region
  - Matched sources colour-coded by catalog
  - Legend, grid, axis labels, and title
  - Saved as PNG alongside the FITS/CSV outputs
  - Optionally displayed in a Tkinter window after the run
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")   # non-interactive backend for generation; we open separately
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from astropy.coordinates import SkyCoord, Galactic, BarycentricTrueEcliptic
import astropy.units as u

from .pipeline import MatchResult
from .footprints import get_footprint


# Colour cycle for catalogs — distinct and colourblind-friendly
CATALOG_COLORS = {
    "abell":  "#E41A1C",   # red
    "sdss":   "#377EB8",   # blue
    "2masx":  "#4DAF4A",   # green
    "ngc":    "#FF7F00",   # orange
    "ned":    "#984EA3",   # purple
    "custom": "#A65628",   # brown
}
DEFAULT_COLOR = "#999999"


# ---------------------------------------------------------------------------
# Footprint boundary sampler
# ---------------------------------------------------------------------------

def _sample_footprint_boundary(footprint: dict, n_points: int = 50_000):
    """
    Generate a cloud of (RA, Dec) points that lie inside the footprint,
    used to shade the survey region on the plot.

    Returns ra_in, dec_in arrays (degrees).
    """
    ftype = footprint["type"]

    if ftype == "circles":
        ra_all, dec_all = [], []
        for field in footprint["fields"]:
            # Random points inside each circular field
            n = max(5000, n_points // len(footprint["fields"]))
            r_max = field["radius_deg"]
            # Sample in polar coords, project to RA/Dec
            r     = r_max * np.sqrt(np.random.uniform(0, 1, n))
            theta = np.random.uniform(0, 2 * np.pi, n)
            dra   = r * np.cos(theta) / np.cos(np.radians(field["dec"]))
            ddec  = r * np.sin(theta)
            ra_all.append(field["ra"]  + dra)
            dec_all.append(field["dec"] + ddec)
        return np.concatenate(ra_all) % 360, np.concatenate(dec_all)

    if ftype == "sky_cuts":
        # Random points over the whole sky, keep those passing the cuts
        ra   = np.random.uniform(0, 360, n_points)
        dec  = np.degrees(np.arcsin(np.random.uniform(-1, 1, n_points)))
        coords  = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
        gal_lat = np.abs(coords.galactic.b.deg)
        ecl_lat = np.abs(coords.transform_to(BarycentricTrueEcliptic()).lat.deg)
        mask = (
            (gal_lat  >= footprint["gal_lat_min"])
            & (ecl_lat >= footprint["ecl_lat_min"])
            & (dec     <= footprint["dec_max"])
        )
        return ra[mask], dec[mask]

    raise ValueError(f"Unknown footprint type: {ftype}")


# ---------------------------------------------------------------------------
# Main plot function
# ---------------------------------------------------------------------------

def make_sky_plot(
    results: list[MatchResult],
    survey_key: str,
    output_dir: str = ".",
    healpix_mask=None,
    healpix_nside: int = None,
) -> str:
    """
    Generate and save a sky plot for a completed cross-match run.

    Parameters
    ----------
    results     : list of MatchResult from pipeline.run_pipeline()
    survey_key  : e.g. "hlwas"
    output_dir  : directory to save the PNG
    healpix_mask, healpix_nside : optional HEALPix mask (passed through for
                                  footprint shading if available)

    Returns
    -------
    png_path : absolute path of the saved PNG, or "" on failure
    """
    footprint = get_footprint(survey_key)

    # Collect matched tables from disk (results only store paths)
    catalog_data = {}   # cat_key -> (ra_array, dec_array)
    for r in results:
        if r.survey.lower() != survey_key.lower():
            continue
        if r.n_matched == 0 or not r.fits_path or not os.path.exists(r.fits_path):
            continue
        try:
            from astropy.table import Table
            t = Table.read(r.fits_path, format="fits")
            ra  = np.array(t["RA"],  dtype=float)
            dec = np.array(t["Dec"], dtype=float)
            # Remove NaNs
            good = np.isfinite(ra) & np.isfinite(dec)
            catalog_data[r.catalog.lower()] = (ra[good], dec[good])
        except Exception as e:
            print(f"  [plot] Could not read {r.fits_path}: {e}")

    if not catalog_data:
        print("  [plot] No matched data to plot.")
        return ""

    # ── Figure setup ────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#0d0d1a")
    ax.set_facecolor("#0d0d1a")

    # ── Footprint shading ───────────────────────────────────────────────────
    print("  [plot] Sampling footprint region…")
    np.random.seed(42)
    fp_ra, fp_dec = _sample_footprint_boundary(footprint)

    # Wrap RA to -180..+180 for a cleaner plot
    fp_ra_wrapped = np.where(fp_ra > 180, fp_ra - 360, fp_ra)

    ax.scatter(
        fp_ra_wrapped, fp_dec,
        s=0.5, c="#1a3a5c", alpha=0.25, linewidths=0,
        rasterized=True, zorder=1,
        label="_footprint",
    )

    # ── Matched sources ─────────────────────────────────────────────────────
    legend_handles = []
    total = 0
    for cat_key, (ra, dec) in catalog_data.items():
        color  = CATALOG_COLORS.get(cat_key, DEFAULT_COLOR)
        ra_w   = np.where(ra > 180, ra - 360, ra)
        n      = len(ra)
        total += n

        # Adjust marker size and alpha for large catalogs
        s     = max(2, min(20, 3000 / max(n, 1)))
        alpha = max(0.4, min(0.9, 500 / max(n, 1)))

        ax.scatter(
            ra_w, dec,
            s=s, c=color, alpha=alpha,
            linewidths=0, zorder=3,
            rasterized=True,
        )
        legend_handles.append(
            Line2D([0], [0], marker="o", color="none",
                   markerfacecolor=color, markersize=7,
                   label=f"{cat_key.upper()}  ({n:,})")
        )

    # Footprint legend entry
    legend_handles.insert(0,
        mpatches.Patch(color="#1a3a5c", alpha=0.6,
                       label=f"{footprint['name']} footprint")
    )

    # ── Axes formatting ─────────────────────────────────────────────────────
    ax.set_xlim(180, -180)   # RA increases to the left (astronomical convention)
    ax.set_ylim(-90, 90)
    ax.set_xlabel("Right Ascension (degrees)", color="white", fontsize=11)
    ax.set_ylabel("Declination (degrees)",     color="white", fontsize=11)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")

    # RA tick labels in hours
    ra_ticks = np.arange(-180, 181, 30)
    ra_labels = [f"{int(r % 360)}°" for r in ra_ticks]
    ax.set_xticks(ra_ticks)
    ax.set_xticklabels(ra_labels, color="white", fontsize=8)
    ax.set_yticks(np.arange(-90, 91, 30))
    ax.tick_params(colors="white", labelsize=8)

    ax.grid(color="#333355", linestyle="--", linewidth=0.5, alpha=0.6)

    ax.set_title(
        f"Roman {footprint['name']} — Cross-Match Results\n"
        f"{total:,} total matched objects",
        color="white", fontsize=13, pad=12,
    )

    legend = ax.legend(
        handles=legend_handles,
        loc="lower left",
        framealpha=0.3,
        facecolor="#111122",
        edgecolor="#444466",
        labelcolor="white",
        fontsize=9,
    )

    plt.tight_layout()

    # ── Save ────────────────────────────────────────────────────────────────
    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(
        output_dir, f"{footprint['name']}_sky_plot.png"
    )
    fig.savefig(png_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  [plot] Saved sky plot: {os.path.abspath(png_path)}")
    return os.path.abspath(png_path)


# ---------------------------------------------------------------------------
# Display in a Tkinter window — pure Tkinter, no Pillow required
# ---------------------------------------------------------------------------

def show_plot_window(png_path: str, title: str = "Sky Plot"):
    """
    Open the saved PNG in a Tkinter Toplevel window using a Canvas.
    Uses only tkinter.PhotoImage — no Pillow or external viewer needed.
    Runs in the calling thread (must be called from the main Tkinter thread
    or via root.after() to be thread-safe).
    """
    import tkinter as tk
    from tkinter import messagebox

    if not os.path.exists(png_path):
        messagebox.showerror("Plot not found", f"Cannot find:\n{png_path}")
        return

    win = tk.Toplevel()
    win.title(title)
    win.configure(bg="#0d0d1a")

    try:
        # tkinter.PhotoImage supports PNG natively in Python 3.6+
        photo = tk.PhotoImage(file=png_path)
    except Exception as e:
        messagebox.showerror("Could not load plot",
                             f"Failed to display image:\n{e}\n\n"
                             f"The PNG was saved to:\n{png_path}")
        win.destroy()
        return

    # Scale window to image size (cap at screen dimensions)
    img_w, img_h = photo.width(), photo.height()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    scale    = min(1.0, (screen_w - 40) / img_w, (screen_h - 80) / img_h)
    disp_w   = int(img_w * scale)
    disp_h   = int(img_h * scale)

    # If scaling needed, subsample (PhotoImage only supports integer subsampling)
    if scale < 1.0:
        factor = max(1, int(1 / scale))
        photo  = photo.subsample(factor, factor)
        disp_w = photo.width()
        disp_h = photo.height()

    canvas = tk.Canvas(win, width=disp_w, height=disp_h,
                       bg="#0d0d1a", highlightthickness=0)
    canvas.pack(padx=8, pady=8)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.image = photo   # keep reference alive

    # Save path label at the bottom
    tk.Label(win, text=f"Saved: {png_path}",
             fg="#888888", bg="#0d0d1a",
             font=("Helvetica", 8)).pack(pady=(0, 6))


def _open_with_os(png_path: str):
    """Open a file with the OS default application (fallback, not used by default)."""
    import subprocess, sys, platform
    try:
        if sys.platform == "win32":
            os.startfile(png_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", png_path])
        else:
            if "microsoft" in platform.release().lower():
                subprocess.run(["explorer.exe", png_path],
                               stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["xdg-open", png_path],
                               stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"  [plot] Could not open plot: {e}")
