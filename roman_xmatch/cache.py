"""
roman_xmatch.cache
==================
Loads pre-built catalog files that ship with the roman-xmatch package.

The .fits.gz files in roman_xmatch/data/ are generated once by
scripts/build_catalogs.py and committed to the repository.  This module
locates them at runtime using importlib.resources so they work correctly
whether the package is installed via pipx, pip, or run from source.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from astropy.table import Table


# ---------------------------------------------------------------------------
# Internal path resolver
# ---------------------------------------------------------------------------

def _data_path(filename: str) -> Path:
    """
    Return the absolute Path to a file in roman_xmatch/data/.
    Works whether the package is installed (zipped wheel) or run from source.
    """
    try:
        # Python 3.9+ preferred API
        ref = resources.files("roman_xmatch") / "data" / filename
        # Materialise to a real path (needed for astropy Table.read)
        with resources.as_file(ref) as p:
            return p
    except Exception:
        # Fallback: assume source layout
        return Path(__file__).parent / "data" / filename


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_bundled(name: str) -> Table:
    """
    Load a pre-built catalog by name (without .fits.gz extension).

    Parameters
    ----------
    name : str
        One of: 'abell', 'mcxc', 'ngc_ugc', '2masx', 'sdss', 'xray_gal'

    Returns
    -------
    Table
        astropy Table with at minimum columns: RA, Dec, catalog, object_id

    Raises
    ------
    FileNotFoundError
        If the bundled file does not exist.  Run scripts/build_catalogs.py
        to generate the data files.
    """
    filename = f"{name}.fits.gz"
    path = _data_path(filename)

    if not path.exists():
        raise FileNotFoundError(
            f"Bundled catalog '{filename}' not found at {path}.\n"
            f"Generate it by running:\n"
            f"    python scripts/build_catalogs.py --catalogs {name}"
        )

    return Table.read(str(path), format="fits")


def bundled_catalogs() -> list[str]:
    """Return the names of all bundled catalogs that exist on disk."""
    data_dir = _data_path(".")
    if not data_dir.exists():
        return []
    return [p.stem.replace(".fits", "")
            for p in sorted(data_dir.glob("*.fits.gz"))]
