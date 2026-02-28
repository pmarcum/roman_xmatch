"""
roman-xmatch
============
Cross-correlate Nancy Grace Roman Space Telescope survey footprints with
major astronomical catalogs.

Quickstart
----------
GUI (browser):
    roman-xmatch

CLI (headless):
    roman-xmatch --cli --survey HLWAS --catalogs abell ngc

Python API:
    from roman_xmatch.pipeline import PipelineOptions, run_pipeline

    opts = PipelineOptions(surveys=["hlwas"], catalogs=["abell", "ngc"])
    results = run_pipeline(opts)
"""

__version__ = "0.1.0"
__author__  = "Roman Footprint Cross-Match Contributors"
