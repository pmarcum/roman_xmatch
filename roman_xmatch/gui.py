"""
roman_xmatch.gui
================
Tkinter-based graphical interface for the Roman footprint cross-match tool.

Follows the same pattern as gooTeX:
  - Log window captures all stdout/stderr output in real time
  - Buttons trigger pipeline functions in background threads (keeps UI responsive)
  - Zero extra dependencies — Tkinter ships with Python on all platforms

Launched automatically when the user runs `roman-xmatch` (no --cli flag).
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

from .footprints import SURVEY_KEYS, SURVEY_LABELS
from .catalogs   import CATALOG_KEYS, CATALOG_LABELS
from .pipeline   import PipelineOptions, run_pipeline



# ---------------------------------------------------------------------------
# Tooltip -- shows a pop-up when the mouse hovers over a widget
# ---------------------------------------------------------------------------

class ToolTip:
    """Lightweight Tkinter tooltip. Attach with ToolTip(widget, text)."""

    DELAY_MS = 600   # ms before tooltip appears
    WRAP_PX  = 340   # text wrap width in pixels

    def __init__(self, widget, text: str):
        self.widget   = widget
        self.text     = text
        self._job     = None
        self._tip_win = None
        widget.bind("<Enter>",  self._schedule)
        widget.bind("<Leave>",  self._cancel)
        widget.bind("<Button>", self._cancel)

    def _schedule(self, event=None):
        self._cancel()
        self._job = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self, event=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        self._hide()

    def _show(self):
        if self._tip_win:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip_win = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self.text, justify="left",
            background="#ffffe0", relief="solid", borderwidth=1,
            wraplength=self.WRAP_PX,
            font=("TkDefaultFont", 9),
            padx=6, pady=4,
        ).pack()

    def _hide(self):
        if self._tip_win:
            self._tip_win.destroy()
            self._tip_win = None


# ---------------------------------------------------------------------------
# stdout/stderr redirector — identical to gooTeX's RedirectText
# ---------------------------------------------------------------------------

class RedirectText:
    def __init__(self, text_widget):
        self.output = text_widget

    def write(self, string):
        self.output.insert(tk.END, string)
        self.output.see(tk.END)
        self.output.update_idletasks()

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# Background task runner — same pattern as gooTeX's run_task()
# ---------------------------------------------------------------------------

def run_task(task_func):
    """Run a pipeline task in a background thread to keep the UI responsive."""
    def wrapper():
        try:
            task_func()
        except SystemExit as e:
            if e.code != 0:
                print("\n❌ Task failed. Review the log above.")
        except Exception as e:
            print(f"\n⚠️  Unexpected error: {e}")

    threading.Thread(target=wrapper, daemon=True).start()


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------

def run_gui():
    root = tk.Tk()
    root.title("Roman Space Telescope — Footprint Cross-Match Tool")
    root.geometry("780x820")
    root.minsize(780, 820)
    root.resizable(True, True)

    # ── Header label (mirrors gooTeX's "Active Project" label) ────────────
    tk.Label(
        root,
        text="Nancy Grace Roman Space Telescope — Catalog Cross-Match",
        font=("Helvetica", 10, "bold"),
        fg="#5f6368",
    ).pack(pady=(10, 0))

    # ── Options frame ──────────────────────────────────────────────────────
    opts_frame = tk.LabelFrame(root, text="Options", padx=10, pady=8)
    opts_frame.pack(padx=12, pady=(8, 0), fill=tk.X)

    # Row 0 — Survey selection
    _SURVEY_TIP = (
        "Select the Roman survey whose sky footprint you want to\n"
        "cross-match against. The footprint defines which region\n"
        "of sky is searched — not which objects were observed.\n"
        "\n"
        "If you have your own custom footprint (e.g. from a\n"
        "specific observing program), you can supply it as a\n"
        "HEALPix mask file instead — see the HEALPix Mask\n"
        "option at the bottom of this panel."
    )
    _survey_lbl = tk.Label(opts_frame, text="Survey:", anchor="w", width=14)
    _survey_lbl.grid(row=0, column=0, sticky="w", pady=3)
    ToolTip(_survey_lbl, _SURVEY_TIP)
    survey_choices = {SURVEY_LABELS[k]: k for k in SURVEY_KEYS}
    survey_choices["All three surveys"] = "all"
    survey_var = tk.StringVar(value=list(survey_choices.keys())[0])
    ttk.Combobox(
        opts_frame,
        textvariable=survey_var,
        values=list(survey_choices.keys()),
        state="readonly",
        width=54,
    ).grid(row=0, column=1, columnspan=3, sticky="w", pady=3)

    # Row 1 — Catalog checkboxes  (2-column layout with section headers)
    _CATALOGS_TIP = (
        "Select one or more catalogs to cross-match against\n"
        "the Roman survey footprint.\n"
        "\n"
        "Sources from each selected catalog that fall within\n"
        "the footprint will be written to separate output files.\n"
        "\n"
        "If the catalog you need is not listed, you can supply\n"
        "your own FITS or CSV file using the Custom File option below."
    )
    _cat_lbl = tk.Label(opts_frame, text="Catalogs:", anchor="w", width=14)
    _cat_lbl.grid(row=1, column=0, sticky="nw", pady=3)
    ToolTip(_cat_lbl, _CATALOGS_TIP)
    cat_frame = tk.Frame(opts_frame)
    cat_frame.grid(row=1, column=1, columnspan=3, sticky="w")
    cat_vars = {}
    defaults_on = {"ngc_ugc"}

    CLUSTER_KEYS = ["abell", "chandra-clusters"]
    GALAXY_KEYS  = [k for k in CATALOG_KEYS if k not in CLUSTER_KEYS and k != "custom"]

    def _section_header(parent, text, grid_row):
        tk.Label(
            parent, text=text,
            font=("TkDefaultFont", 9, "bold"),
            anchor="w",
        ).grid(row=grid_row, column=0, columnspan=2, sticky="w", pady=(6, 1))

    def _add_checkboxes(parent, keys, start_row):
        for i, key in enumerate(keys):
            var = tk.BooleanVar(value=(key in defaults_on))
            cat_vars[key] = var
            tk.Checkbutton(
                parent,
                text=CATALOG_LABELS[key],
                variable=var,
            ).grid(row=start_row + i // 2, column=i % 2, sticky="w", padx=(0, 16))
        return start_row + (len(keys) + 1) // 2   # return next free row

    _section_header(cat_frame, "— Clusters —", 0)
    next_row = _add_checkboxes(cat_frame, CLUSTER_KEYS, 1)
    _section_header(cat_frame, "— Galaxies —", next_row)
    _add_checkboxes(cat_frame, GALAXY_KEYS, next_row + 1)

    # Row 1b — AND/OR toggle + tolerance (sits below catalog checkboxes)
    match_mode_var = tk.StringVar(value="OR")
    tol_var        = tk.StringVar(value="5.0")

    mode_frame = tk.Frame(opts_frame)
    mode_frame.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 2))

    _MATCH_TIP = (
        "OR  (union): sources from each catalog are recorded\n"
        "independently. The output contains everything found\n"
        "in any of the selected catalogs.\n"
        "\n"
        "AND  (intersection): only sources that appear in ALL\n"
        "selected catalogs within the specified tolerance are\n"
        "kept. The anchor catalog is the first one checked.\n"
        "Extra columns show the matched ID and separation\n"
        "(in arcsec) for each additional catalog."
    )
    _match_lbl = tk.Label(mode_frame, text="Catalog match:", anchor="w", width=14)
    _match_lbl.pack(side=tk.LEFT)
    ToolTip(_match_lbl, _MATCH_TIP)

    or_btn = tk.Radiobutton(
        mode_frame, text="OR  (union)",
        variable=match_mode_var, value="OR",
    )
    or_btn.pack(side=tk.LEFT, padx=(0, 8))

    and_btn = tk.Radiobutton(
        mode_frame, text="AND  (intersection)",
        variable=match_mode_var, value="AND",
    )
    and_btn.pack(side=tk.LEFT, padx=(0, 12))

    tk.Label(mode_frame, text="Tolerance:").pack(side=tk.LEFT)
    tol_entry = tk.Entry(mode_frame, textvariable=tol_var, width=5)
    tol_entry.pack(side=tk.LEFT, padx=(4, 2))
    tk.Label(mode_frame, text="arcsec").pack(side=tk.LEFT)

    def _update_tol_state(*_):
        state = tk.NORMAL if match_mode_var.get() == "AND" else tk.DISABLED
        tol_entry.config(state=state)
    match_mode_var.trace_add("write", _update_tol_state)
    _update_tol_state()   # set initial state

    # Row 2 — Custom catalog file
    _CUSTOM_TIP = (
        "Accepted file formats: FITS or CSV.\n"
        "\n"
        "Coordinate formats supported:\n"
        "  Decimal degrees (recommended)\n"
        "    RA:  215.831      Dec:  34.811\n"
        "\n"
        "  Sexagesimal strings\n"
        "    RA:  14:23:19.6   Dec:  +34:48:40\n"
        "    RA:  14 23 19.6   Dec:  +34 48 40\n"
        "\n"
        "RA sexagesimal is interpreted as h:m:s.\n"
        "Dec sexagesimal is interpreted as d:m:s.\n"
        "\n"
        "Default column names: RA, Dec\n"
        "(override below if your file uses different names)."
    )
    _custom_lbl = tk.Label(opts_frame, text="Custom file:", anchor="w", width=14)
    _custom_lbl.grid(row=3, column=0, sticky="w", pady=3)
    ToolTip(_custom_lbl, _CUSTOM_TIP)
    custom_path_var  = tk.StringVar(value="")
    custom_check_var = tk.BooleanVar(value=False)
    tk.Entry(opts_frame, textvariable=custom_path_var, width=42).grid(
        row=3, column=1, sticky="w", pady=3)

    def browse_custom():
        path = filedialog.askopenfilename(
            title="Select custom catalog",
            filetypes=[("FITS files", "*.fits *.fit"),
                       ("CSV files",  "*.csv"),
                       ("All files",  "*.*")],
        )
        if path:
            custom_path_var.set(path)
            custom_check_var.set(True)

    tk.Checkbutton(opts_frame, text="Include", variable=custom_check_var).grid(
        row=3, column=2, sticky="w")
    tk.Button(opts_frame, text="Browse…", command=browse_custom).grid(
        row=3, column=3, sticky="w", padx=(4, 0))

    # Row 3 — RA / Dec column names for custom file
    tk.Label(opts_frame, text="RA / Dec cols:", anchor="w", width=14).grid(
        row=4, column=0, sticky="w", pady=2)
    ra_col_var  = tk.StringVar(value="RA")
    dec_col_var = tk.StringVar(value="Dec")
    col_sub = tk.Frame(opts_frame)
    col_sub.grid(row=4, column=1, sticky="w")
    tk.Entry(col_sub, textvariable=ra_col_var,  width=10).pack(side=tk.LEFT, padx=(0, 6))
    tk.Entry(col_sub, textvariable=dec_col_var, width=10).pack(side=tk.LEFT)

    # Row 4 — HEALPix mask (optional)
    _HEALPIX_TIP = (
        "Optional: provide a HEALPix mask file (.fits) that defines\n"
        "a custom survey footprint.\n"
        "\n"
        "When supplied, this mask is used as the footprint instead\n"
        "of the Survey selection above. Any pixel with a non-zero\n"
        "value in the mask is treated as inside the footprint.\n"
        "\n"
        "Use this for custom observing programs, simulated surveys,\n"
        "or any region not covered by the standard Survey options."
    )
    _healpix_lbl = tk.Label(opts_frame, text="HEALPix mask:", anchor="w", width=14)
    _healpix_lbl.grid(row=6, column=0, sticky="w", pady=3)
    ToolTip(_healpix_lbl, _HEALPIX_TIP)
    mask_path_var = tk.StringVar(value="")
    tk.Entry(opts_frame, textvariable=mask_path_var, width=42).grid(
        row=6, column=1, sticky="w", pady=3)

    def browse_mask():
        path = filedialog.askopenfilename(
            title="Select HEALPix mask",
            filetypes=[("FITS files", "*.fits *.fit"), ("All files", "*.*")],
        )
        if path:
            mask_path_var.set(path)

    tk.Button(opts_frame, text="Browse…", command=browse_mask).grid(
        row=5, column=3, sticky="w", padx=(4, 0))
    tk.Label(opts_frame,
             text="(optional — uses built-in approximation if blank)",
             fg="#888888", font=("Helvetica", 8)).grid(
        row=5, column=1, columnspan=2, sticky="e")

    # Row 5 — Output directory + row limit
    tk.Label(opts_frame, text="Output folder:", anchor="w", width=14).grid(
        row=5, column=0, sticky="w", pady=3)
    output_dir_var = tk.StringVar(value="roman_xmatch_output")
    tk.Entry(opts_frame, textvariable=output_dir_var, width=32).grid(
        row=5, column=1, sticky="w", pady=3)
    tk.Label(opts_frame, text="Row limit:", anchor="e").grid(
        row=6, column=2, sticky="e", padx=(10, 4))
    row_limit_var = tk.StringVar(value="100000")
    tk.Entry(opts_frame, textvariable=row_limit_var, width=10).grid(
        row=6, column=3, sticky="w")

    # ── Log window (same as gooTeX) ─────────────────────────────────────────
    log_area = scrolledtext.ScrolledText(
        root, wrap=tk.WORD, height=18, font=("Courier", 9))
    log_area.pack(padx=12, pady=(10, 0), fill=tk.BOTH, expand=True)

    # Redirect stdout + stderr into the log window
    sys.stdout = RedirectText(log_area)
    sys.stderr = RedirectText(log_area)

    # ── Button row (mirrors gooTeX's btn_frame) ─────────────────────────────
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)

    def get_options():
        """Read widget state and return a PipelineOptions object, or None on error."""
        survey_key = survey_choices[survey_var.get()]
        catalogs   = [k for k, v in cat_vars.items() if v.get()]

        if custom_check_var.get():
            if not custom_path_var.get():
                messagebox.showwarning(
                    "Custom catalog",
                    "Please select a custom catalog file, or uncheck 'Include'.")
                return None
            catalogs.append("custom")

        if not catalogs:
            messagebox.showwarning("No catalogs selected",
                                   "Please select at least one catalog.")
            return None

        try:
            row_limit = int(row_limit_var.get())
        except ValueError:
            messagebox.showwarning("Row limit", "Row limit must be a whole number.")
            return None

        try:
            tol = float(tol_var.get())
            if tol <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Tolerance", "Tolerance must be a positive number.")
            return None

        return PipelineOptions(
            surveys                 = [survey_key],
            catalogs                = catalogs,
            mask_path               = mask_path_var.get() or None,
            output_dir              = output_dir_var.get() or "roman_xmatch_output",
            row_limit               = row_limit,
            custom_file             = custom_path_var.get() or None,
            custom_ra_col           = ra_col_var.get()  or "RA",
            custom_dec_col          = dec_col_var.get() or "Dec",
            match_mode              = match_mode_var.get(),
            match_tolerance_arcsec  = tol,
        )

    # Track the most recently generated plot so the button can find it
    last_plot = {"path": None, "survey_key": None, "results": None, "catalog_order": [], "tolerance_arcsec": 5.0}

    def do_run():
        opts = get_options()
        if opts is None:
            return
        log_area.delete("1.0", tk.END)
        print("🔭 Starting Roman footprint cross-match…\n")

        def on_plot_ready(png_path, survey_key):
            """Store the plot path + context and enable the View Plot button."""
            last_plot["path"]       = png_path
            last_plot["survey_key"] = survey_key
            plot_btn.config(state=tk.NORMAL)

        def on_run_complete(results):
            last_plot["results"]         = results
            last_plot["catalog_order"]   = opts.catalogs
            last_plot["tolerance_arcsec"]= opts.match_tolerance_arcsec

        opts.plot_callback = on_plot_ready
        run_task(lambda: on_run_complete(run_pipeline(opts, log=print)))

    def do_open_output():
        """Open the output folder in the system file manager."""
        import subprocess, platform
        folder = os.path.abspath(output_dir_var.get() or "roman_xmatch_output")
        if not os.path.exists(folder):
            messagebox.showinfo(
                "Output folder",
                f"Folder does not exist yet:\n{folder}\n\nRun a cross-match first.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder])
            else:
                if "microsoft" in platform.release().lower():
                    subprocess.run(["explorer.exe", folder],
                                   stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["xdg-open", folder],
                                   stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"⚠️  Could not open folder: {e}")

    def do_view_plot():
        """Open the interactive sky plot in a Tkinter window."""
        png_path   = last_plot.get("path", "")
        survey_key = last_plot.get("survey_key")
        results    = last_plot.get("results")
        if not png_path or not os.path.exists(png_path):
            messagebox.showinfo("No plot",
                                "No sky plot available yet.\nRun a cross-match first.")
            return
        from .plotting import show_plot_window
        show_plot_window(png_path, title="Roman \u2014 Sky Plot",
                         results=results, survey_key=survey_key,
                         catalog_order=last_plot.get("catalog_order", []),
                         tolerance_arcsec=last_plot.get("tolerance_arcsec", 5.0))

    def do_clear_log():
        log_area.delete("1.0", tk.END)

    # Buttons — same colour scheme as gooTeX
    tk.Button(
        btn_frame, text="🚀 Run Cross-Match",
        command=do_run,
        bg="#4CAF50", fg="white", width=18, pady=5,
    ).pack(side=tk.LEFT, padx=5)

    tk.Button(
        btn_frame, text="📂 Open Output Folder",
        command=do_open_output,
        bg="#2196F3", fg="white", width=18, pady=5,
    ).pack(side=tk.LEFT, padx=5)

    plot_btn = tk.Button(
        btn_frame, text="🌌 View Sky Plot",
        command=do_view_plot,
        bg="#9C27B0", fg="white", width=14, pady=5,
        state=tk.DISABLED,   # enabled automatically when a plot is ready
    )
    plot_btn.pack(side=tk.LEFT, padx=5)

    tk.Button(
        btn_frame, text="🗑  Clear Log",
        command=do_clear_log,
        bg="#f1f3f4", fg="black", width=12, pady=5,
    ).pack(side=tk.LEFT, padx=5)

    root.mainloop()


if __name__ == "__main__":
    run_gui()
