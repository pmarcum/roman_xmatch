"""
roman_xmatch.cli
================
Command-line interface.

  roman-xmatch                      → launches the Streamlit GUI
  roman-xmatch --cli [options]      → headless pipeline, no browser
"""

import argparse
import sys

from .pipeline import PipelineOptions, run_pipeline
from .footprints import SURVEY_KEYS
from .catalogs   import CATALOG_KEYS


def launch_gui():
    """Launch the Tkinter GUI window."""
    try:
        from .gui import run_gui
        run_gui()
    except Exception as e:
        print(f"[ERROR] Could not launch GUI: {e}")
        print("Try running in headless mode instead:  roman-xmatch --cli")
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="roman-xmatch",
        description=(
            "Roman Space Telescope — footprint cross-match tool.\n\n"
            "Without --cli, opens an interactive browser-based GUI.\n"
            "With --cli, runs the pipeline headlessly from the terminal."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--cli",
        action="store_true",
        help="Run in headless command-line mode (no browser / no GUI).",
    )
    p.add_argument(
        "--survey", "-s",
        default="hlwas",
        help=(
            f"Survey footprint: {' | '.join(SURVEY_KEYS)} | all  "
            "(default: hlwas)"
        ),
    )
    p.add_argument(
        "--catalogs", "-c",
        nargs="+",
        default=["abell", "ngc"],
        help=(
            f"Catalogs to query: {' | '.join(CATALOG_KEYS)} | all  "
            "(default: abell ngc)"
        ),
    )
    p.add_argument(
        "--mask", "-m",
        default=None,
        metavar="MASK_FILE",
        help="Path to a HEALPix FITS mask file (overrides built-in footprint).",
    )
    p.add_argument(
        "--output-dir", "-o",
        default="roman_xmatch_output",
        metavar="DIR",
        help="Output directory for FITS / CSV files (default: roman_xmatch_output/).",
    )
    p.add_argument(
        "--row-limit", "-r",
        type=int,
        default=100_000,
        metavar="N",
        help="Max rows per catalog query (default: 100000).",
    )
    p.add_argument(
        "--custom-file",
        default=None,
        metavar="FILE",
        help="Path to a custom catalog file (FITS or CSV).",
    )
    p.add_argument(
        "--custom-ra-col",
        default="RA",
        metavar="COL",
        help="RA column name in the custom catalog file (default: RA).",
    )
    p.add_argument(
        "--custom-dec-col",
        default="Dec",
        metavar="COL",
        help="Dec column name in the custom catalog file (default: Dec).",
    )
    return p


def main():
    parser = build_parser()
    args   = parser.parse_args()

    # ── GUI mode (default) ────────────────────────────────────────────────
    if not args.cli:
        launch_gui()
        return

    # ── CLI / headless mode ───────────────────────────────────────────────
    surveys  = ["all"] if args.survey.lower() == "all" else [args.survey.lower()]
    catalogs = args.catalogs

    opts = PipelineOptions(
        surveys        = surveys,
        catalogs       = catalogs,
        mask_path      = args.mask,
        output_dir     = args.output_dir,
        row_limit      = args.row_limit,
        custom_file    = args.custom_file,
        custom_ra_col  = args.custom_ra_col,
        custom_dec_col = args.custom_dec_col,
    )

    print("\n" + "="*60)
    print("  Roman Space Telescope — Footprint Cross-Match Tool")
    print("="*60)
    print(f"  Mode     : CLI (headless)")
    print(f"  Survey   : {args.survey.upper()}")
    print(f"  Catalogs : {', '.join(c.upper() for c in catalogs)}")
    print(f"  Output   : {args.output_dir}/")
    print("="*60 + "\n")

    run_pipeline(opts, log=print)


if __name__ == "__main__":
    main()
