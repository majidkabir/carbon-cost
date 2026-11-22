#!/usr/bin/env python3
"""Publishes a data workflow's datasets that differ from tariffs/data only
in what OpenStreetMap gives: where a charge object is (its geometry, the
booths' names and headings) and the extract's date (the carbon-cost
extension's osm_extract, and the date a method text gives for the
extract). Anything else, a new dataset included, is left for review.

Usage: python3 tools/orct/publish.py <workflow orct dir> tariffs/data
       python3 tools/orct/publish.py --crossings <workflow ferries dir> ferries/data
         (ferry crossings files that differ only in the terminals' positions)
       python3 tools/orct/publish.py --fx <workflow fx dir> fx/data
         (exchange rate files that only add days after the last one: the
         same header, every committed row unchanged)

Prints what it published and a ::warning for each dataset to review, and
rebuilds tariffs/data/index.json when it published something. Exit 0.
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert  # noqa: E402

# A charge object's location parts that come from OpenStreetMap.
OSM_LOCATION = {"geometry", "point_names", "headings"}
EXT = "io.github.majidkabir.carboncost"
# "(extract of 2026-11-08)", "OpenStreetMap's toll booths (2026-11-08T21:21:00Z)".
OSM_DATE = re.compile(r"(OpenStreetMap[^.;]{0,120}?)\d{4}-\d\d-\d\d(?:T[\d:]+Z)?")


def placed(loc):
    """Whether a location has a point to match routes to."""
    g = (loc or {}).get("geometry") or {}
    return bool(g.get("coordinates"))


def osm_only(a, b, path=()):
    """True if a and b (the committed dataset and the new one) differ only in
    OpenStreetMap's parts. An object that loses its place (OpenStreetMap no
    longer has its booths) is not: that is for review."""
    if path == ("extensions", EXT, "osm_extract"):
        return True
    if len(path) == 4 and path[0] == "charge_objects" and path[2] == "location" and path[3] in OSM_LOCATION:
        return True
    if len(path) == 3 and path[0] == "charge_objects" and path[2] == "location" and placed(a) and not placed(b):
        return False
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if len(path) == 3 and path[0] == "charge_objects" and path[2] == "location":
            # OpenStreetMap's parts may come or go (headings, booth names).
            a = {k: v for k, v in a.items() if k not in OSM_LOCATION}
            b = {k: v for k, v in b.items() if k not in OSM_LOCATION}
        return a.keys() == b.keys() and all(osm_only(a[k], b[k], path + (k,)) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(osm_only(x, y, path + (i,)) for i, (x, y) in enumerate(zip(a, b)))
    if isinstance(a, str) and path and path[-1] == "method":
        return OSM_DATE.sub(r"\1D", a) == OSM_DATE.sub(r"\1D", b)
    return a == b


def main(new, data):
    published, review = [], []
    for cc in sorted(os.listdir(new)):
        if not os.path.isdir(os.path.join(new, cc)):
            continue
        for name in sorted(os.listdir(os.path.join(new, cc))):
            if not name.endswith(".orct.json"):
                continue
            f = os.path.join(cc, name)
            src, dst = os.path.join(new, f), os.path.join(data, f)
            if not os.path.exists(dst):
                review.append((f, "new dataset"))
                continue
            a, b = open(dst, "rb").read(), open(src, "rb").read()
            if a == b:
                continue
            if osm_only(json.loads(a), json.loads(b)):
                shutil.copy(src, dst)
                published.append(f)
            else:
                review.append((f, "differs in more than OpenStreetMap's positions and extract date"))
    for f in published:
        print("published", f)
    for f, why in review:
        print(f"::warning title={f}::{why}; not published, review it")
    if published:
        print(convert.write_index(data), "datasets in the index")
    return published, review


def terminals_only(a, b, path=()):
    """True if two ferry crossings files differ only in their terminals'
    positions (lat, lon), which come from OpenStreetMap's ferry lines."""
    if len(path) >= 2 and path[-2] == "terminals" and isinstance(a, dict) and isinstance(b, dict):
        a = {k: v for k, v in a.items() if k not in ("lat", "lon")}
        b = {k: v for k, v in b.items() if k not in ("lat", "lon")}
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(terminals_only(a[k], b[k], path + (k,)) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(terminals_only(x, y, path + (i,)) for i, (x, y) in enumerate(zip(a, b)))
    return a == b


def crossings(new, data):
    """Publishes a data workflow's ferry crossings files (crossings-*.json)
    that differ from ferries/data only in the terminals' positions."""
    for name in sorted(os.listdir(new)):
        src, dst = os.path.join(new, name), os.path.join(data, name)
        if not (name.startswith("crossings-") and name.endswith(".json")) or not os.path.exists(dst):
            continue
        a, b = open(dst, "rb").read(), open(src, "rb").read()
        if a == b:
            continue
        if terminals_only(json.loads(a), json.loads(b)):
            shutil.copy(src, dst)
            print("published", "ferries/" + name)
        else:
            print(f"::warning title=ferries/{name}::differs in more than OpenStreetMap's positions; not published, review it")


FX_FILES = ("ecb-hist.csv", "nbs-eur-rsd.csv", "boa-eur-all.csv")


def appended_days(a, b):
    """True if rate file b is a, with only rows for later days added."""
    old, new = a.splitlines(), b.splitlines()
    if len(new) <= len(old) or new[:len(old)] != old or len(old) < 2:
        return False
    last = old[-1].split(",")[0]
    days = [r.split(",")[0] for r in new[len(old):]]
    return all(re.fullmatch(r"\d{4}-\d\d-\d\d", d) for d in days) and days == sorted(set(days)) and days[0] > last


def fx(new, data):
    """Publishes the History data workflow's exchange rate files
    (fx/data/*.csv) that only add days: a past rate changed, a currency
    added or a day removed is left for review."""
    for name in FX_FILES:
        src, dst = os.path.join(new, name), os.path.join(data, name)
        if not (os.path.exists(src) and os.path.exists(dst)):
            continue
        a, b = open(dst, encoding="utf-8").read(), open(src, encoding="utf-8").read()
        if a == b:
            continue
        if appended_days(a, b):
            shutil.copy(src, dst)
            print("published", "fx/" + name, "to", b.splitlines()[-1].split(",")[0])
        else:
            print(f"::warning title=fx/{name}::differs in more than new days; not published, review it")


if __name__ == "__main__":
    if sys.argv[1] == "--fx":
        fx(*sys.argv[2:])
    elif sys.argv[1] == "--crossings":
        crossings(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
