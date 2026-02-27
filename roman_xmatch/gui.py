"""
roman_xmatch.gui
================
Streamlit-based graphical interface for the Roman footprint cross-match tool.

Launched automatically when the user runs  `roman-xmatch`  (no --cli flag).
"""

import os
import sys
import tempfile
import threading
import queue
from pathlib import Path

import streamlit as st

from .footprints import SURVEY_KEYS, SURVEY_LABELS
from .catalogs   import CATALOG_KEYS, CATALOG_LABELS
from .pipeline   import PipelineOptions, run_pipeline, MatchResult


# ---------------------------------------------------------------------------
# Page config — must be first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Roman Footprint Cross-Match",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    /* Sidebar header */
    [data-testid="stSidebar"] h1 { font-size: 1.2rem; }

    /* Result cards */
    .result-card {
        border-left: 4px solid #1f77b4;
        padding: 0.6rem 1rem;
        margin-bottom: 0.5rem;
        background: #f0f4fa;
        border-radius: 4px;
    }
    .result-card.error {
        border-left-color: #d62728;
        background: #fff0f0;
    }
    .result-card.empty {
        border-left-color: #aaa;
        background: #f8f8f8;
    }

    /* Progress log */
    .log-box {
        font-family: monospace;
        font-size: 0.82rem;
        background: #1e1e1e;
        color: #d4d4d4;
        padding: 1rem;
        border-radius: 6px;
        max-height: 320px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_state():
    defaults = {
        "running":     False,
        "log_lines":   [],
        "results":     [],
        "run_counter": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ---------------------------------------------------------------------------
# Sidebar — all controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image(
        "https://roman.gsfc.nasa.gov/images/Roman_SpaceTelescope_logo.png",
        use_container_width=True,
    )
    st.title("Roman Footprint\nCross-Match Tool")
    st.caption("Nancy Grace Roman Space Telescope")
    st.divider()

    # ── Survey selection ──────────────────────────────────────────────────
    st.subheader("1 · Survey")
    survey_options = {SURVEY_LABELS[k]: k for k in SURVEY_KEYS}
    survey_options["All three surveys"] = "all"

    selected_survey_label = st.selectbox(
        "Survey footprint",
        options=list(survey_options.keys()),
        index=0,
        help="Select the Roman Core Community Survey footprint to use.",
    )
    survey_choice = survey_options[selected_survey_label]

    # ── HEALPix mask override ─────────────────────────────────────────────
    with st.expander("Upload HEALPix mask (optional)"):
        mask_file = st.file_uploader(
            "HEALPix FITS mask",
            type=["fits", "fit"],
            help="Upload an official Roman HEALPix mask file to replace the "
                 "built-in sky-cut approximation.",
        )
        if mask_file:
            st.success(f"Mask loaded: {mask_file.name}")

    st.divider()

    # ── Catalog selection ─────────────────────────────────────────────────
    st.subheader("2 · Catalogs")
    selected_cats = st.multiselect(
        "Catalogs to cross-match",
        options=CATALOG_KEYS,
        default=["abell", "ngc"],
        format_func=lambda k: CATALOG_LABELS[k],
        help="Select one or more catalogs to query.",
    )

    use_custom = "custom" in selected_cats
    custom_file_upload = None
    custom_ra_col  = "RA"
    custom_dec_col = "Dec"

    if use_custom:
        with st.expander("Custom catalog settings", expanded=True):
            custom_file_upload = st.file_uploader(
                "Upload catalog (FITS or CSV)",
                type=["fits", "fit", "csv"],
            )
            custom_ra_col  = st.text_input("RA column name",  value="RA")
            custom_dec_col = st.text_input("Dec column name", value="Dec")

    st.divider()

    # ── Advanced options ──────────────────────────────────────────────────
    st.subheader("3 · Options")
    row_limit = st.number_input(
        "Max rows per catalog query",
        min_value=100,
        max_value=2_000_000,
        value=100_000,
        step=10_000,
        help="Reduce for quick tests; increase for completeness.",
    )

    output_dir = st.text_input(
        "Output directory",
        value="roman_xmatch_output",
        help="Folder where FITS and CSV results will be saved.",
    )

    st.divider()

    # ── Run button ────────────────────────────────────────────────────────
    run_disabled = (
        st.session_state["running"]
        or not selected_cats
        or (use_custom and custom_file_upload is None)
    )
    run_button = st.button(
        "▶  Run Cross-Match",
        disabled=run_disabled,
        use_container_width=True,
        type="primary",
    )

    if not selected_cats:
        st.caption("⚠ Select at least one catalog.")
    if use_custom and custom_file_upload is None:
        st.caption("⚠ Upload a custom catalog file.")


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

st.title("🔭 Roman Space Telescope — Footprint Cross-Match")
st.caption(
    "Cross-correlates Roman survey footprints with major astronomical catalogs "
    "and outputs matched objects as FITS and CSV files."
)

tab_run, tab_results, tab_about = st.tabs(["▶ Run", "📋 Results", "ℹ About"])

# ── About tab ─────────────────────────────────────────────────────────────
with tab_about:
    st.markdown("""
### About this tool

**roman-xmatch** cross-correlates the planned survey footprints of the
[Nancy Grace Roman Space Telescope](https://roman.gsfc.nasa.gov/) with
major astronomical object catalogs, producing filtered lists of objects
that lie within each footprint.

#### Surveys
| Key | Name | Area |
|-----|------|------|
| HLWAS | High Latitude Wide Area Survey | ~5,000 deg² |
| HLTDS | High Latitude Time Domain Survey | ~18 deg² (2 fields) |
| GBTDS | Galactic Bulge Time Domain Survey | ~2 deg² (6 pointings) |

The footprints are approximated from the **ROTAC Final Report (April 2025)**.
When Roman releases official HEALPix mask files, upload them in the sidebar
to replace the built-in approximations.

#### Catalogs
| Key | Source |
|-----|--------|
| Abell clusters | VizieR VII/110A |
| SDSS photometric | VizieR II/294 |
| 2MASX | VizieR VII/233 |
| NGC/IC | VizieR VII/118 |
| NED | NASA/IPAC Extragalactic Database |
| Custom | Your own FITS or CSV file |

#### Outputs
Results are saved as both `.fits` and `.csv` files in the output directory,
one file per survey × catalog combination.

#### Citation
If you use this tool, please cite the ROTAC Final Report and the relevant
catalog papers (Abell 1958, Skrutskie et al. 2006, etc.).
    """)

# ── Run tab ───────────────────────────────────────────────────────────────
with tab_run:
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Configuration summary")
        surveys_display = (
            [survey_choice.upper()]
            if survey_choice != "all"
            else [k.upper() for k in SURVEY_KEYS]
        )
        st.markdown(f"**Survey(s):** {', '.join(surveys_display)}")
        st.markdown(
            f"**Catalogs:** "
            + ", ".join(CATALOG_LABELS[c] for c in selected_cats if c != "custom")
            + (f", Custom ({custom_file_upload.name if custom_file_upload else '—'})"
               if use_custom else "")
        )
        st.markdown(f"**Row limit:** {row_limit:,}")
        st.markdown(f"**Output dir:** `{output_dir}/`")
        st.markdown(
            f"**Mask:** `{mask_file.name}`" if mask_file
            else "**Mask:** built-in approximation"
        )

    with col_right:
        st.subheader("Footprint description")
        if survey_choice == "all":
            for k in SURVEY_KEYS:
                st.markdown(f"- {SURVEY_LABELS[k]}")
        else:
            st.markdown(SURVEY_LABELS[survey_choice])
            if survey_choice == "hlwas":
                st.info(
                    "HLWAS is approximated using Galactic latitude (|b|>20°), "
                    "Ecliptic latitude (|β|>15°), and Dec < +30° cuts, based "
                    "on the April 2025 ROTAC report."
                )

    st.divider()

    log_placeholder    = st.empty()
    status_placeholder = st.empty()

    def render_log(lines):
        log_placeholder.markdown(
            f'<div class="log-box">' + "\n".join(lines[-80:]) + "</div>",
            unsafe_allow_html=True,
        )

    # ── Handle run ────────────────────────────────────────────────────────
    if run_button:
        st.session_state["running"]   = True
        st.session_state["log_lines"] = ["Starting cross-match pipeline…"]
        st.session_state["results"]   = []
        st.session_state["run_counter"] += 1

        # Save uploaded files to temp paths
        mask_tmp   = None
        custom_tmp = None

        if mask_file:
            mask_tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".fits"
            )
            mask_tmp.write(mask_file.read())
            mask_tmp.flush()

        if use_custom and custom_file_upload:
            suffix = Path(custom_file_upload.name).suffix
            custom_tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            )
            custom_tmp.write(custom_file_upload.read())
            custom_tmp.flush()

        opts = PipelineOptions(
            surveys       = ["all"] if survey_choice == "all" else [survey_choice],
            catalogs      = selected_cats,
            mask_path     = mask_tmp.name  if mask_tmp   else None,
            output_dir    = output_dir,
            row_limit     = int(row_limit),
            custom_file   = custom_tmp.name if custom_tmp else None,
            custom_ra_col = custom_ra_col,
            custom_dec_col= custom_dec_col,
        )

        msg_queue: queue.Queue[str | None] = queue.Queue()

        def _worker():
            def _log(msg):
                msg_queue.put(str(msg))
            try:
                results = run_pipeline(opts, log=_log)
                st.session_state["results"] = results
            except Exception as exc:
                msg_queue.put(f"FATAL ERROR: {exc}")
            finally:
                msg_queue.put(None)   # sentinel

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        # Drain the queue while the worker runs, updating the log live
        while True:
            try:
                msg = msg_queue.get(timeout=0.2)
            except queue.Empty:
                render_log(st.session_state["log_lines"])
                continue
            if msg is None:
                break
            st.session_state["log_lines"].append(msg)
            render_log(st.session_state["log_lines"])

        thread.join()
        st.session_state["running"] = False

        # Clean up temp files
        for f in [mask_tmp, custom_tmp]:
            if f:
                try:
                    os.unlink(f.name)
                except Exception:
                    pass

        status_placeholder.success("✅ Cross-match complete!  See the Results tab.")
        render_log(st.session_state["log_lines"])

    elif st.session_state["log_lines"]:
        render_log(st.session_state["log_lines"])


# ── Results tab ───────────────────────────────────────────────────────────
with tab_results:
    results: list[MatchResult] = st.session_state.get("results", [])

    if not results:
        st.info("No results yet — run the cross-match first.")
    else:
        total_matched = sum(r.n_matched for r in results)
        st.metric("Total matched objects", f"{total_matched:,}")
        st.divider()

        for r in results:
            label = f"{r.survey.upper()} × {r.catalog.upper()}"

            if r.error:
                st.markdown(
                    f'<div class="result-card error">'
                    f"<b>{label}</b> — ❌ Error: {r.error}</div>",
                    unsafe_allow_html=True,
                )
            elif r.n_matched == 0:
                st.markdown(
                    f'<div class="result-card empty">'
                    f"<b>{label}</b> — 0 matches "
                    f"(retrieved {r.n_retrieved:,})</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="result-card">'
                    f"<b>{label}</b> — "
                    f"✅ <b>{r.n_matched:,}</b> matches "
                    f"(from {r.n_retrieved:,} retrieved)</div>",
                    unsafe_allow_html=True,
                )
                col1, col2 = st.columns(2)
                if r.fits_path and os.path.exists(r.fits_path):
                    with open(r.fits_path, "rb") as fh:
                        col1.download_button(
                            label=f"⬇ Download FITS",
                            data=fh.read(),
                            file_name=os.path.basename(r.fits_path),
                            mime="application/octet-stream",
                            key=f"fits_{r.survey}_{r.catalog}",
                        )
                if r.csv_path and os.path.exists(r.csv_path):
                    with open(r.csv_path, "rb") as fh:
                        col2.download_button(
                            label=f"⬇ Download CSV",
                            data=fh.read(),
                            file_name=os.path.basename(r.csv_path),
                            mime="text/csv",
                            key=f"csv_{r.survey}_{r.catalog}",
                        )


def main():
    """Entry point — called by the `roman-xmatch` command."""
    pass   # Streamlit runs the module directly; this is a no-op placeholder.
