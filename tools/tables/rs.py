"""Builds Serbia's toll table from the decision in force
(tools/rs/gazette.py): the putarina decision as amended in Službeni
glasnik RS 57/2026, applying from 1 July 2026 (fetch.py's rs-sg-57-2026.pdf,
its scanned tables read by tools/rs/gazette_ocr.py into rs-sg-57-2026.json),
with Serbia's OpenStreetMap toll booths (the workflow's rs-osm.geojsonseq).
The table is held to JP Putevi Srbije's current price list (rs-cene.pdf,
read with pdftotext -layout): its RSD amounts must be the same on every pair
the list has.

The list's heading names its first day ("važi od"). A list from another
day means a new amendment: then this file must name it (and the table in
force become history, tools/history/build_rs_gazette.py).

Usage: python3 rs.py fetched/ out-dir -> out-dir/rs-<date>.json
"""
import importlib.util, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rs_gazette", os.path.join(HERE, "..", "rs", "gazette.py"))
gz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gz)
SOURCES = {s["id"]: s["url"] for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}

MONTHS = {"januara": 1, "februara": 2, "marta": 3, "aprila": 4, "maja": 5, "juna": 6, "jula": 7, "avgusta": 8,
          "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}
# The amendment in force: its source, the issue, the day it applies from,
# and stations that start later (that day).
SID, ISSUE, FROM, LATER = "rs-sg-57-2026", "57/2026", "2026-07-01", {}


def main(fetched, out):
    txt = os.path.join(fetched, "rs-cene.txt")
    subprocess.run(["pdftotext", "-layout", os.path.join(fetched, "rs-cene.pdf"), txt], check=True)
    text = open(txt, encoding="utf-8").read()
    m = re.search(r"važi od:?\s*(\d+)\.\s*([a-zčćšđž]+)\s+(\d{4})", text)
    if not m or m.group(2) not in MONTHS:
        sys.exit("rs-cene.pdf: no 'važi od' date")
    start = f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    if start != FROM:
        sys.exit(f"rs-cene.pdf: a price list from {start}, not {FROM}: a new amendment, for tools/tables/rs.py")
    g = json.load(open(os.path.join(fetched, SID + ".json"), encoding="utf-8"))
    bs = gz.booths(os.path.join(fetched, "rs-osm.geojsonseq"))
    made = gz.tables(g, os.path.join(fetched, SID + ".pdf"), SID, ISSUE, SOURCES[SID], FROM, None, LATER, bs)
    gz.check(made[-1][1], txt, f"{SID} and rs-cene")
    os.makedirs(out, exist_ok=True)
    for first, tb in made:
        tb["law"] += f" Held to Putevi Srbije's current price list (its RSD amounts, from {start}): the same on every pair it has."
        tb["sources"].append({"title": "JP Putevi Srbije: toll price list (PDF), whose RSD amounts the table is held to", "url": SOURCES["rs-cene"]})
        tb["osm_extract"] = open(os.path.join(fetched, "rs-osm-timestamp.txt")).read().strip()[:10]
        json.dump(tb, open(os.path.join(out, f"rs-{first}.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
