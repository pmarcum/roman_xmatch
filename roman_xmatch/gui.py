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
    root.geometry("780x660")
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
    tk.Label(opts_frame, text="Survey:", anchor="w", width=14).grid(
        row=0, column=0, sticky="w", pady=3)
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

    # Row 1 — Catalog checkboxes
    tk.Label(opts_frame, text="Catalogs:", anchor="w", width=14).grid(
        row=1, column=0, sticky="nw", pady=3)
    cat_frame = tk.Frame(opts_frame)
    cat_frame.grid(row=1, column=1, columnspan=3, sticky="w")
    cat_vars = {}
    defaults_on = {"abell", "ngc"}
    std_cats = [k for k in CATALOG_KEYS if k != "custom"]
    for i, key in enumerate(std_cats):
        var = tk.BooleanVar(value=(key in defaults_on))
        cat_vars[key] = var
        tk.Checkbutton(
            cat_frame,
            text=CATALOG_LABELS[key],
            variable=var,
        ).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 16))

    # Row 2 — Custom catalog file
    tk.Label(opts_frame, text="Custom file:", anchor="w", width=14).grid(
        row=2, column=0, sticky="w", pady=3)
    custom_path_var  = tk.StringVar(value="")
    custom_check_var = tk.BooleanVar(value=False)
    tk.Entry(opts_frame, textvariable=custom_path_var, width=42).grid(
        row=2, column=1, sticky="w", pady=3)

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
        row=2, column=2, sticky="w")
    tk.Button(opts_frame, text="Browse…", command=browse_custom).grid(
        row=2, column=3, sticky="w", padx=(4, 0))

    # Row 3 — RA / Dec column names for custom file
    tk.Label(opts_frame, text="RA / Dec cols:", anchor="w", width=14).grid(
        row=3, column=0, sticky="w", pady=2)
    ra_col_var  = tk.StringVar(value="RA")
    dec_col_var = tk.StringVar(value="Dec")
    col_sub = tk.Frame(opts_frame)
    col_sub.grid(row=3, column=1, sticky="w")
    tk.Entry(col_sub, textvariable=ra_col_var,  width=10).pack(side=tk.LEFT, padx=(0, 6))
    tk.Entry(col_sub, textvariable=dec_col_var, width=10).pack(side=tk.LEFT)

    # Row 4 — HEALPix mask (optional)
    tk.Label(opts_frame, text="HEALPix mask:", anchor="w", width=14).grid(
        row=4, column=0, sticky="w", pady=3)
    mask_path_var = tk.StringVar(value="")
    tk.Entry(opts_frame, textvariable=mask_path_var, width=42).grid(
        row=4, column=1, sticky="w", pady=3)

    def browse_mask():
        path = filedialog.askopenfilename(
            title="Select HEALPix mask",
            filetypes=[("FITS files", "*.fits *.fit"), ("All files", "*.*")],
        )
        if path:
            mask_path_var.set(path)

    tk.Button(opts_frame, text="Browse…", command=browse_mask).grid(
        row=4, column=3, sticky="w", padx=(4, 0))
    tk.Label(opts_frame,
             text="(optional — uses built-in approximation if blank)",
             fg="#888888", font=("Helvetica", 8)).grid(
        row=4, column=1, columnspan=2, sticky="e")

    # Row 5 — Output directory + row limit
    tk.Label(opts_frame, text="Output folder:", anchor="w", width=14).grid(
        row=5, column=0, sticky="w", pady=3)
    output_dir_var = tk.StringVar(value="roman_xmatch_output")
    tk.Entry(opts_frame, textvariable=output_dir_var, width=32).grid(
        row=5, column=1, sticky="w", pady=3)
    tk.Label(opts_frame, text="Row limit:", anchor="e").grid(
        row=5, column=2, sticky="e", padx=(10, 4))
    row_limit_var = tk.StringVar(value="100000")
    tk.Entry(opts_frame, textvariable=row_limit_var, width=10).grid(
        row=5, column=3, sticky="w")

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

        return PipelineOptions(
            surveys        = [survey_key],
            catalogs       = catalogs,
            mask_path      = mask_path_var.get() or None,
            output_dir     = output_dir_var.get() or "roman_xmatch_output",
            row_limit      = row_limit,
            custom_file    = custom_path_var.get() or None,
            custom_ra_col  = ra_col_var.get()  or "RA",
            custom_dec_col = dec_col_var.get() or "Dec",
        )

    def do_run():
        opts = get_options()
        if opts is None:
            return
        log_area.delete("1.0", tk.END)
        print("🔭 Starting Roman footprint cross-match…\n")
        run_task(lambda: run_pipeline(opts, log=print))

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

    tk.Button(
        btn_frame, text="🗑  Clear Log",
        command=do_clear_log,
        bg="#f1f3f4", fg="black", width=12, pady=5,
    ).pack(side=tk.LEFT, padx=5)

    root.mainloop()


if __name__ == "__main__":
    run_gui()
