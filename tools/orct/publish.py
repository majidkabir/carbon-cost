#!/usr/bin/env python3
"""Publishes a data workflow's datasets that differ from tariffs/data only
in what OpenStreetMap gives: where a charge object is (its geometry, the
booths' names and headings) and the extract's date (the carbon-cost
extension's osm_extract, and the date a method text gives for the
extract). Anything else, a new dataset included, is left for review.

Usage: python3 tools/orct/publish.py <workflow orct dir> tariffs/data

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


def osm_only(a, b, path=()):
    """True if a and b differ only in OpenStreetMap's parts."""
    if path == ("extensions", EXT, "osm_extract"):
        return True
    if len(path) == 4 and path[0] == "charge_objects" and path[2] == "location" and path[3] in OSM_LOCATION:
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
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


if __name__ == "__main__":
    main(*sys.argv[1:])
