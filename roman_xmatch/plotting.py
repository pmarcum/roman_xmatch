"""
roman_xmatch.plotting
=====================
Interactive sky plots of matched sources overlaid on the Roman survey footprint.

Features:
  - Embedded matplotlib figure with full zoom/pan toolbar
  - Object labels appear automatically when zoomed in sufficiently
  - Label density is catalog-aware (clusters always, dense catalogs only when close)
  - Dark theme, color-coded by catalog
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")   # used for static PNG generation
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from astropy.coordinates import SkyCoord, BarycentricTrueEcliptic
import astropy.units as u

from .pipeline import MatchResult
from .footprints import get_footprint


# ---------------------------------------------------------------------------
# Catalog display config
# ---------------------------------------------------------------------------

CATALOG_COLORS = {
    "abell":            "#FF4444",   # bright red
    "sdss":             "#FFD700",   # gold
    "2masx":            "#00FF88",   # bright green
    "ngc_ugc":          "#FF8C00",   # orange
    "xray_gal":         "#00BFFF",   # deep sky blue
    "chandra-clusters": "#FF69B4",   # hot pink
    "custom":           "#FFFFFF",   # white
}
DEFAULT_COLOR = "#FFFF00"

CATALOG_MARKERS = {
    "abell":            "^",   # triangle up
    "chandra-clusters": "D",   # diamond
    "sdss":             ".",   # pixel dot
    "2masx":            "s",   # square
    "ngc_ugc":          "o",   # circle
    "xray_gal":         "+",   # plus cross
    "custom":           "*",   # star
}
DEFAULT_MARKER = "o"

# Zoom threshold (degrees of view width) below which labels appear
LABEL_ZOOM_THRESHOLD = {
    "abell":            360,   # always
    "chandra-clusters": 360,   # always
    "xray_gal":         360,   # always
    "ngc_ugc":          20,    # medium zoom
    "2masx":            5,     # close zoom
    "sdss":             3,     # very close zoom
    "custom":           10,
}

MAX_LABELS = 80   # cap to avoid clutter even when zoomed way in


# ---------------------------------------------------------------------------
# Label formatters  (object_id → short display string)
# ---------------------------------------------------------------------------

def _format_label(cat_key: str, object_id: str, ra: float, dec: float) -> str:
    """Return a short, human-readable label for one source."""
    oid = str(object_id).strip()

    if cat_key == "abell":
        # "ACO_426" → "426"
        return oid.replace("ACO_", "")

    if cat_key == "chandra-clusters":
        # "MCXC_J0000.1+0816" → "0000.1+0816"
        return oid.replace("MCXC_", "").lstrip("J")

    if cat_key == "ngc_ugc":
        # "NGC_7801"  → "N7801"
        # "NGC_I5370" → "I5370"
        # "UGC_891"   → "U891"
        if oid.startswith("UGC_"):
            return "U" + oid[4:]
        if oid.startswith("NGC_"):
            inner = oid[4:]
            if inner.startswith("I"):
                return inner          # already "I5370"
            return "N" + inner        # "N7801"
        return oid

    if cat_key == "xray_gal":
        # "4XMM_J123456.7+..." → "123456.7+..." (9 chars)
        # "CXO J123456.7+..."  → "123456.7+..." (9 chars)
        s = oid
        for prefix in ("4XMM_J", "4XMM_", "CXO J", "CXO_J", "CXO_"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        s = s.lstrip("J")
        return s[:9]

    if cat_key == "2masx":
        # "2MASX J12345678+..." → "12345678..." (9 chars)
        s = oid
        for prefix in ("2MASX J", "2MASX_J", "2MASX "):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        s = s.lstrip("J")
        return s[:9]

    if cat_key == "sdss":
        # Derive from coordinates: "123.5+12.3"
        sign = "+" if dec >= 0 else "-"
        return f"{ra:.1f}{sign}{abs(dec):.1f}"

    return oid[:9]


# ---------------------------------------------------------------------------
# Footprint polygon builders
# ---------------------------------------------------------------------------

def _circle_polygon(ra_c, dec_c, radius_deg, n=180):
    theta   = np.linspace(0, 2 * np.pi, n)
    cos_d   = max(np.cos(np.radians(dec_c)), 0.01)
    ra  = (ra_c  + radius_deg * np.cos(theta) / cos_d) % 360
    dec =  dec_c + radius_deg * np.sin(theta)
    return np.clip(ra, 0, 360), np.clip(dec, -90, 90)


def _sky_cuts_patches(footprint: dict, n_ra: int = 720):
    gal_min  = footprint["gal_lat_min"]
    ecl_min  = footprint["ecl_lat_min"]
    dec_max  = footprint["dec_max"]
    dec_fine = np.linspace(-90, dec_max, 1800)
    d_ra     = 360.0 / n_ra
    patches  = []

    for ra in np.linspace(0, 360, n_ra, endpoint=False):
        coords  = SkyCoord(ra=np.full_like(dec_fine, ra) * u.deg,
                           dec=dec_fine * u.deg, frame="icrs")
        gal_lat = np.abs(coords.galactic.b.deg)
        ecl_lat = np.abs(coords.transform_to(BarycentricTrueEcliptic()).lat.deg)
        inside  = (gal_lat >= gal_min) & (ecl_lat >= ecl_min)

        transitions = np.diff(inside.astype(int))
        starts = list(np.where(transitions ==  1)[0] + 1)
        ends   = list(np.where(transitions == -1)[0] + 1)
        if inside[0]:  starts = [0] + starts
        if inside[-1]: ends   = ends + [len(dec_fine) - 1]

        ra_w = ra if ra <= 180 else ra - 360
        for s, e in zip(starts, ends):
            dec_lo = dec_fine[s]
            dec_hi = dec_fine[min(e, len(dec_fine) - 1)]
            patches.append((
                [ra_w, ra_w - d_ra, ra_w - d_ra, ra_w, ra_w],
                [dec_lo, dec_lo, dec_hi, dec_hi, dec_lo],
            ))
    return patches


# ---------------------------------------------------------------------------
# Main plot builder  (returns fig + ax + catalog_data for interactive use)
# ---------------------------------------------------------------------------

def _build_figure(catalog_data: dict, footprint: dict):
    """
    Build and return (fig, ax, scatter_artists) without displaying or saving.
    scatter_artists maps cat_key → (ra_w_array, dec_array, ids_array, PathCollection)
    """
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor("#0d0d1a")
    ax.set_facecolor("#0d0d1a")

    # ── Footprint ──────────────────────────────────────────────────────────
    fp_color = "#4488aa"
    if footprint["type"] == "circles":
        for field in footprint["fields"]:
            ra_v, dec_v = _circle_polygon(field["ra"], field["dec"],
                                          field["radius_deg"])
            ra_v_w = np.where(ra_v > 180, ra_v - 360, ra_v)
            ax.fill(ra_v_w, dec_v, color=fp_color, alpha=0.30,
                    linewidth=0.8, edgecolor="#6699bb", zorder=1)

    elif footprint["type"] == "sky_cuts":
        from matplotlib.collections import PolyCollection
        patches = _sky_cuts_patches(footprint)
        verts = [list(zip(rv, dv)) for rv, dv in patches]
        pc = PolyCollection(verts, facecolor=fp_color, alpha=0.30,
                            edgecolor="none", linewidth=0, zorder=1)
        ax.add_collection(pc)

    # ── Sources ────────────────────────────────────────────────────────────
    legend_handles = [
        mpatches.Patch(color=fp_color, alpha=0.6,
                       label=f"{footprint['name']} footprint")
    ]
    scatter_artists = {}   # cat_key → (ra_w, dec, ids, artist)
    total = 0

    for cat_key, (ra, dec, ids, suppress) in catalog_data.items():
        color  = CATALOG_COLORS.get(cat_key, DEFAULT_COLOR)
        marker = CATALOG_MARKERS.get(cat_key, DEFAULT_MARKER)
        ra_w   = np.where(ra > 180, ra - 360, ra)
        n      = len(ra)
        total += n
        # Size scales with catalog density but has a generous floor
        s      = max(25, min(150, 200000 / max(n, 1)))
        is_line_marker = marker in ("+", "x", "|", "_")
        if is_line_marker:
            # Line markers: use facecolor=color with full alpha so arms are visible,
            # but draw with thicker linewidth for overlap visibility
            sc = ax.scatter(ra_w, dec, s=s * 1.8,
                            c=color,
                            marker=marker,
                            alpha=0.7,
                            linewidths=2.0,
                            zorder=3,
                            rasterized=(n > 10_000))
        else:
            # Filled markers: semi-transparent face, no edge
            sc = ax.scatter(ra_w, dec, s=s,
                            c=color,
                            edgecolors="none",
                            marker=marker,
                            alpha=0.45,
                            zorder=3,
                            rasterized=(n > 10_000))
        scatter_artists[cat_key] = (ra_w, dec, ids, sc, suppress)

        legend_handles.append(
            Line2D([0], [0], marker=marker, color="none",
                   markerfacecolor=color if not is_line_marker else "none",
                   markeredgecolor=color if is_line_marker else "none",
                   markeredgewidth=2.0 if is_line_marker else 0,
                   markersize=10 if is_line_marker else 9,
                   label=f"{cat_key.upper()}  ({n:,})")
        )

    # ── Axes ───────────────────────────────────────────────────────────────
    ax.set_xlim(180, -180)
    ax.set_ylim(-90, 90)
    ax.set_xlabel("Right Ascension (degrees)", color="white", fontsize=11)
    ax.set_ylabel("Declination (degrees)",     color="white", fontsize=11)
    ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")

    ra_ticks = np.arange(-180, 181, 30)
    ax.set_xticks(ra_ticks)
    ax.set_xticklabels([f"{int(r % 360)}°" for r in ra_ticks],
                       color="white", fontsize=8)
    ax.set_yticks(np.arange(-90, 91, 30))

    # Custom cursor format: sexagesimal + decimal degrees on one line
    def _fmt_coord(x, y):
        from astropy.coordinates import Angle
        import astropy.units as u
        ra_deg = x % 360
        ra_sex  = Angle(ra_deg * u.deg).to_string(unit=u.hour,   sep=":", precision=1, pad=True)
        dec_sex = Angle(y      * u.deg).to_string(unit=u.degree, sep=":", precision=0, pad=True, alwayssign=True)
        sign = "+" if y >= 0 else ""
        return f"RA {ra_sex}  Dec {dec_sex}    ({ra_deg:.4f}°,  {sign}{y:.4f}°)"
    ax.format_coord = _fmt_coord
    ax.grid(color="#333355", linestyle="--", linewidth=0.5, alpha=0.6)
    ax.set_title(
        f"Roman {footprint['name']} — Cross-Match Results\n"
        f"{total:,} total matched objects",
        color="white", fontsize=13, pad=12,
    )
    ax.legend(handles=legend_handles, loc="lower left",
              framealpha=0.3, facecolor="#111122",
              edgecolor="#444466", labelcolor="white", fontsize=9)

    fig.tight_layout()
    return fig, ax, scatter_artists


# ---------------------------------------------------------------------------
# Label manager — updates annotations on zoom/pan
# ---------------------------------------------------------------------------

class _LabelManager:
    def __init__(self, ax, scatter_artists: dict):
        self.ax       = ax
        self.artists  = scatter_artists   # cat_key -> (ra_w, dec, ids, sc)
        self._labels  = []                # active Text objects
        self.enabled  = False             # toggled by user

    def _clear(self):
        for txt in self._labels:
            try:
                txt.remove()
            except Exception:
                pass
        self._labels.clear()

    def toggle(self):
        """Enable or disable labels and refresh."""
        self.enabled = not self.enabled
        self.update()

    def update(self, event=None):
        self._clear()
        if not self.enabled:
            self.ax.figure.canvas.draw_idle()
            return

        ax   = self.ax
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        ra_lo  = min(xlim); ra_hi  = max(xlim)
        dec_lo = ylim[0];   dec_hi = ylim[1]

        # Track positions already labeled (in display coords) to avoid overlap
        # between catalogs — first catalog in priority order wins the label
        labeled_ra  = []
        labeled_dec = []
        tol_deg = (ra_hi - ra_lo) * 0.015   # ~1.5% of view width

        label_count = 0
        for cat_key, (ra_w, dec, ids, _, suppress) in self.artists.items():
            in_view = (
                (ra_w  >= ra_lo) & (ra_w  <= ra_hi) &
                (dec   >= dec_lo) & (dec   <= dec_hi)
            )
            # Only label sources not suppressed by a higher-priority catalog
            in_view = in_view & ~suppress
            idx = np.where(in_view)[0]
            if len(idx) == 0:
                continue

            # Thin out if too many visible points
            slots  = max(1, MAX_LABELS - label_count)
            stride = max(1, len(idx) // slots)
            idx    = idx[::stride][:slots]

            color = CATALOG_COLORS.get(cat_key, DEFAULT_COLOR)
            for i in idx:
                # Skip if a higher-priority catalog already labeled this position
                if labeled_ra:
                    dra  = np.abs(np.array(labeled_ra)  - ra_w[i])
                    ddec = np.abs(np.array(labeled_dec) - dec[i])
                    if np.any((dra < tol_deg) & (ddec < tol_deg)):
                        continue
                lbl = _format_label(cat_key, ids[i], ra_w[i], dec[i])
                txt = ax.text(
                    ra_w[i], dec[i], f" {lbl}",
                    color=color, fontsize=7,
                    ha="left", va="center",
                    clip_on=True, zorder=10,
                )
                self._labels.append(txt)
                labeled_ra.append(ra_w[i])
                labeled_dec.append(dec[i])
                label_count += 1
                if label_count >= MAX_LABELS:
                    break

        ax.figure.canvas.draw_idle()


# ---------------------------------------------------------------------------
# Public: generate static PNG
# ---------------------------------------------------------------------------

def make_sky_plot(
    results: list,
    survey_key: str,
    output_dir: str = ".",
    healpix_mask=None,
    healpix_nside: int = None,
) -> str:
    footprint    = get_footprint(survey_key)
    catalog_data = _load_catalog_data(results, survey_key)
    if not catalog_data:
        print("  [plot] No matched data to plot.")
        return ""

    fig, ax, _ = _build_figure(catalog_data, footprint)

    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, f"{footprint['name']}_sky_plot.png")
    fig.savefig(png_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  [plot] Saved: {os.path.abspath(png_path)}")
    return os.path.abspath(png_path)


# ---------------------------------------------------------------------------
# Public: interactive Tkinter window with zoom/pan + labels
# ---------------------------------------------------------------------------

def show_plot_window(png_path: str, title: str = "Sky Plot",
                     results: list = None, survey_key: str = None,
                     catalog_order: list = None, tolerance_arcsec: float = 5.0):
    """
    Open an interactive matplotlib figure embedded in a Tkinter window.

    If results + survey_key are provided, the plot is fully interactive
    (zoom, pan, auto-labels).  Otherwise falls back to displaying the PNG.
    """
    import tkinter as tk
    from tkinter import messagebox

    if results is None or survey_key is None:
        # Fallback: static PNG display
        _show_static(png_path, title)
        return

    footprint    = get_footprint(survey_key)
    print(f"  [plot] results={len(results) if results else None}, survey={survey_key}")
    catalog_data = _load_catalog_data(results, survey_key,
                                      catalog_order=catalog_order or [],
                                      tolerance_arcsec=tolerance_arcsec)
    print(f"  [plot] Interactive mode: {len(catalog_data)} catalogs loaded: {list(catalog_data.keys())}")
    if not catalog_data:
        print("  [plot] No catalog data — falling back to static PNG.")
        _show_static(png_path, title)
        return

    # Import TkAgg canvas directly — no need to switch global backend
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

    win = tk.Toplevel()
    win.title(title)
    win.configure(bg="#0d0d1a")

    fig, ax, scatter_artists = _build_figure(catalog_data, footprint)

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # Single compact button bar — all controls in one row
    btn_bar = tk.Frame(win, bg="#1a1a2e", pady=3)
    btn_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ── Mouse navigation ──────────────────────────────────────────────────
    # Scroll wheel: zoom in/out centred on cursor
    # Left-click drag: pan
    _pan_state = {"active": False, "x": None, "y": None,
                  "xlim": None, "ylim": None}

    def _on_scroll(event):
        if event.inaxes != ax:
            return
        factor = 0.85 if event.button == "up" else 1.0 / 0.85
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        # Zoom centred on cursor position
        xc, yc = event.xdata, event.ydata
        ax.set_xlim([xc + (x - xc) * factor for x in xlim])
        ax.set_ylim([yc + (y - yc) * factor for y in ylim])
        canvas.draw_idle()

    def _on_press(event):
        if event.inaxes != ax or event.button not in (1, 3):
            return
        _pan_state["active"] = True
        _pan_state["x"]    = event.xdata
        _pan_state["y"]    = event.ydata
        _pan_state["xlim"] = ax.get_xlim()
        _pan_state["ylim"] = ax.get_ylim()

    def _on_release(event):
        _pan_state["active"] = False

    def _on_motion(event):
        if not _pan_state["active"] or event.inaxes != ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        dx = event.xdata - _pan_state["x"]
        dy = event.ydata - _pan_state["y"]
        ax.set_xlim([x - dx for x in _pan_state["xlim"]])
        ax.set_ylim([y - dy for y in _pan_state["ylim"]])
        canvas.draw_idle()

    canvas.mpl_connect("scroll_event",         _on_scroll)
    canvas.mpl_connect("button_press_event",   _on_press)
    canvas.mpl_connect("button_release_event", _on_release)
    canvas.mpl_connect("motion_notify_event",  _on_motion)

    # ── Label manager ─────────────────────────────────────────────────────
    lm = _LabelManager(ax, scatter_artists)
    ax.callbacks.connect("xlim_changed", lm.update)
    ax.callbacks.connect("ylim_changed", lm.update)

    # Label toggle button
    label_btn_var = tk.StringVar(value="Labels: OFF")
    def _toggle_labels():
        lm.toggle()
        label_btn_var.set("Labels: ON" if lm.enabled else "Labels: OFF")
        lbl_btn.config(
            bg="#2a6e2a" if lm.enabled else "#3a3a5a",
            relief=tk.SUNKEN if lm.enabled else tk.RAISED,
        )

    lbl_btn = tk.Button(
        btn_bar,
        textvariable=label_btn_var,
        command=_toggle_labels,
        bg="#3a3a5a", fg="white",
        relief=tk.RAISED,
        font=("Helvetica", 9),
        padx=8,
    )
    lbl_btn.pack(side=tk.LEFT, padx=(8, 0), pady=2)

    # Export View button — dumps visible objects to CSV
    def _export_view():
        import csv
        from tkinter import filedialog, messagebox
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        ra_lo, ra_hi = min(xlim), max(xlim)
        dec_lo, dec_hi = ylim[0], ylim[1]

        rows = []
        for cat_key, (ra_w, dec, ids, _, _suppress) in scatter_artists.items():
            in_view = (
                (ra_w  >= ra_lo) & (ra_w  <= ra_hi) &
                (dec   >= dec_lo) & (dec  <= dec_hi)
            )
            idx = np.where(in_view)[0]
            for i in idx:
                rows.append({
                    "catalog":   cat_key,
                    "object_id": ids[i],
                    "RA_deg":    f"{ra_w[i] % 360:.6f}",
                    "Dec_deg":   f"{dec[i]:.6f}",
                    "label":     _format_label(cat_key, ids[i], ra_w[i] % 360, dec[i]),
                })

        if not rows:
            messagebox.showinfo("Export View", "No objects in the current view.")
            return

        ra_lo_360  = ra_lo % 360
        ra_hi_360  = ra_hi % 360
        default_fn = (
            f"objects_RA{ra_lo_360:.1f}-{ra_hi_360:.1f}"
            f"_Dec{dec_lo:.1f}-{dec_hi:.1f}.csv"
        ).replace("+", "").replace(" ", "")
        out_path = filedialog.asksaveasfilename(
            title="Save visible objects",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_fn,
        )
        if not out_path:
            return

        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["catalog","object_id","RA_deg","Dec_deg","label"])
            writer.writeheader()
            writer.writerows(rows)

        messagebox.showinfo("Export View",
            f"{len(rows):,} objects written to:\n{out_path}")

    # Save Figure button — replaces the unreliable matplotlib icon
    def _save_figure():
        from tkinter import filedialog
        out_path = filedialog.asksaveasfilename(
            title="Save figure",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("PDF file", "*.pdf"),
                       ("SVG file", "*.svg"), ("All files", "*.*")],
            initialfile="sky_plot.png",
        )
        if out_path:
            fig.savefig(out_path, dpi=150, bbox_inches="tight",
                        facecolor=fig.get_facecolor())

    tk.Button(
        btn_bar,
        text="Save Figure…",
        command=_save_figure,
        bg="#3a3a5a", fg="white",
        relief=tk.RAISED,
        font=("Helvetica", 9),
        padx=8,
    ).pack(side=tk.LEFT, padx=(4, 0))

    tk.Button(
        btn_bar,
        text="Save Objects in View…",
        command=_export_view,
        bg="#3a3a5a", fg="white",
        relief=tk.RAISED,
        font=("Helvetica", 9),
        padx=8,
    ).pack(side=tk.LEFT, padx=(4, 0))

    # Coord display label on right side of button bar
    coord_var = tk.StringVar(value="")
    tk.Label(btn_bar, textvariable=coord_var, fg="#aaaacc", bg="#1a1a2e",
             font=("Courier", 9)).pack(side=tk.RIGHT, padx=8)

    def _on_mouse_move(event):
        if event.inaxes == ax and event.xdata is not None:
            coord_var.set(ax.format_coord(event.xdata, event.ydata))
        else:
            coord_var.set("")
    canvas.mpl_connect("motion_notify_event", _on_mouse_move)

    # Status bar
    tk.Label(win, text=f"Saved: {png_path}",
             fg="#666688", bg="#0d0d1a",
             font=("Helvetica", 8)).pack(pady=(0, 4))

    win.protocol("WM_DELETE_WINDOW", lambda: (plt.close(fig), win.destroy()))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_catalog_data(results: list, survey_key: str,
                       catalog_order: list = None,
                       tolerance_arcsec: float = 5.0) -> dict:
    """
    Load matched FITS/CSV files and return
        {cat_key: (ra, dec, ids, suppress)} dict.

    All dots are always plotted at their true positions.
    suppress[i] = True means source i's label should be suppressed because
    a higher-priority catalog source lies within tolerance_arcsec.
    """
    from astropy.table import Table
    raw = {}   # cat_key -> (ra, dec, ids)

    def _priority(r):
        key = r.catalog.lower()
        if catalog_order:
            try: return catalog_order.index(key)
            except ValueError: return 999
        return 0
    ordered = sorted([r for r in results if r.survey.lower() == survey_key.lower()],
                     key=_priority)

    for r in ordered:
        if r.n_matched == 0:
            print(f"  [plot] Skipping {r.catalog} — n_matched=0")
            continue
        load_path = None
        if r.fits_path and os.path.exists(r.fits_path):
            load_path = (r.fits_path, "fits")
        elif hasattr(r, "csv_path") and r.csv_path and os.path.exists(r.csv_path):
            load_path = (r.csv_path, "csv")
        if load_path is None:
            print(f"  [plot] Skipping {r.catalog} — no FITS or CSV found")
            continue
        try:
            t = Table.read(load_path[0], format=load_path[1])
            print(f"  [plot] Loaded {r.catalog}: {len(t)} rows")
            ra  = np.array(t["RA"],  dtype=float)
            dec = np.array(t["Dec"], dtype=float)
            id_col = "object_id" if "object_id" in t.colnames else t.colnames[3]
            ids = np.array(t[id_col]).astype(str)
            good = np.isfinite(ra) & np.isfinite(dec)
            raw[r.catalog.lower()] = (ra[good], dec[good], ids[good])
        except Exception as e:
            print(f"  [plot] Could not read {load_path[0]}: {e}")

    # Build suppress arrays — all dots plotted, only labels suppressed
    tol_rad   = np.radians(tolerance_arcsec / 3600.0)
    prior_ra  = np.empty(0)
    prior_dec = np.empty(0)
    catalog_data = {}

    for cat_key, (ra, dec, ids) in raw.items():
        suppress = np.zeros(len(ra), dtype=bool)
        if len(prior_ra) > 0 and len(raw) > 1:
            ra_r  = np.radians(ra)
            dec_r = np.radians(dec)
            CHUNK = 2_000
            for start in range(0, len(ra), CHUNK):
                end   = min(start + CHUNK, len(ra))
                a_ra  = ra_r [start:end, np.newaxis]
                a_dec = dec_r[start:end, np.newaxis]
                dra   = prior_ra  - a_ra
                ddec  = prior_dec - a_dec
                hav   = (np.sin(ddec / 2) ** 2 +
                         np.cos(a_dec) * np.cos(prior_dec) * np.sin(dra / 2) ** 2)
                sep   = 2 * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))
                suppress[start:end] = np.any(sep < tol_rad, axis=1)
            n_sup = int(suppress.sum())
            print(f"  [plot] {cat_key}: {n_sup:,} labels suppressed (within {tolerance_arcsec}'' of higher-priority source)")
        catalog_data[cat_key] = (ra, dec, ids, suppress)
        prior_ra  = np.concatenate([prior_ra,  np.radians(ra)])
        prior_dec = np.concatenate([prior_dec, np.radians(dec)])

    return catalog_data


def _show_static(png_path: str, title: str):
    """Fallback: display saved PNG in a plain Tkinter window."""
    import tkinter as tk
    from tkinter import messagebox
    if not os.path.exists(png_path):
        messagebox.showerror("Plot not found", f"Cannot find:\n{png_path}")
        return
    win = tk.Toplevel()
    win.title(title)
    win.configure(bg="#0d0d1a")
    try:
        photo = tk.PhotoImage(file=png_path)
    except Exception as e:
        messagebox.showerror("Could not load plot", str(e))
        win.destroy()
        return
    img_w, img_h = photo.width(), photo.height()
    screen_w     = win.winfo_screenwidth()
    screen_h     = win.winfo_screenheight()
    scale        = min(1.0, (screen_w - 40) / img_w, (screen_h - 80) / img_h)
    if scale < 1.0:
        factor = max(1, int(1 / scale))
        photo  = photo.subsample(factor, factor)
    canvas = tk.Canvas(win, width=photo.width(), height=photo.height(),
                       bg="#0d0d1a", highlightthickness=0)
    canvas.pack(padx=8, pady=8)
    canvas.create_image(0, 0, anchor="nw", image=photo)
    canvas.image = photo
    tk.Label(win, text=f"Saved: {png_path}",
             fg="#888888", bg="#0d0d1a",
             font=("Helvetica", 8)).pack(pady=(0, 6))
