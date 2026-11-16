"""Builds Serbia's toll table from JP Putevi Srbije's current price list
(fetch.py's rs-cene.pdf, read with pdftotext -layout) and Serbia's
OpenStreetMap toll booths (the workflow's rs-osm.geojsonseq), with
tools/rs/build.py.

The list's heading names its first day ("važi od"). tools/rs/build.py's
law text and dates are those of the list from 1 July 2026, so a list from
another day stops the build: a new price list, for which that text must
be updated (and the current table become history, tools/history/build_rs.py).

Usage: python3 rs.py fetched/ out-dir -> out-dir/rs-<date>.json
"""
import importlib.util, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rs_build", os.path.join(HERE, "..", "rs", "build.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

MONTHS = {"januara": 1, "februara": 2, "marta": 3, "aprila": 4, "maja": 5, "juna": 6, "jula": 7, "avgusta": 8,
          "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}
LIST_FROM = "2026-07-01"  # the list tools/rs/build.py describes


def main(fetched, out):
    txt = os.path.join(fetched, "rs-cene.txt")
    subprocess.run(["pdftotext", "-layout", os.path.join(fetched, "rs-cene.pdf"), txt], check=True)
    text = open(txt, encoding="utf-8").read()
    m = re.search(r"važi od:?\s*(\d+)\.\s*([a-zčćšđž]+)\s+(\d{4})", text)
    if not m or m.group(2) not in MONTHS:
        sys.exit("rs-cene.pdf: no 'važi od' date")
    start = f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    if start != LIST_FROM:
        sys.exit(f"rs-cene.pdf: a price list from {start}, not {LIST_FROM}: update tools/rs/build.py")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"rs-{start}.json")
    rs.main(txt, os.path.join(fetched, "rs-osm.geojsonseq"), path)
    t = json.load(open(path, encoding="utf-8"))
    assert t["valid_from"] == start, t["valid_from"]


if __name__ == "__main__":
    main(*sys.argv[1:])
