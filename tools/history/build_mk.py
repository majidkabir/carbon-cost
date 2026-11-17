"""Builds North Macedonia's toll table from 1 January 2024 to 30 April 2025
(Службен весник 118/2019, art. 5, transcribed in
tools/tables/transcribed/mk-2019.json) with tools/tables/mk.py and the
OpenStreetMap extract the history workflow copies into fetched/osm.

Usage: python3 build_mk.py fetched/ out-dir"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import mk  # noqa: E402

if __name__ == "__main__":
    fetched, out = sys.argv[1:]
    mk.main(os.path.join(HERE, "..", "tables", "transcribed", "mk-2019.json"), os.path.join(fetched, "osm"), out)
