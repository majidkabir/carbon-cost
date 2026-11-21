"""Tests of publish.osm_only and publish.appended_days: python3 tools/orct/test_publish.py"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish import appended_days, osm_only  # noqa: E402

BASE = {
    "dataset": {"id": "x/2026-01-01", "method": "Stations placed at OpenStreetMap's toll booths (extract of 2026-11-08); law of 2025-12-18."},
    "charge_objects": [{"id": "a", "type": "station", "name": "A",
                        "location": {"geometry": {"type": "MultiPoint", "coordinates": [[1.0, 2.0]]}, "point_names": ["A"]}}],
    "charges": [{"id": "c", "rates": [{"amount": 1.25}]}],
    "extensions": {"io.github.majidkabir.carboncost": {"osm_extract": "2026-11-08"}},
}


def changed(f):
    d = copy.deepcopy(BASE)
    f(d)
    return osm_only(json.loads(json.dumps(BASE)), d)


def set_(path, value):
    def f(d):
        x = d
        for k in path[:-1]:
            x = x[k]
        x[path[-1]] = value
    return f


CASES = [
    ("same", lambda d: None, True),
    ("extract date", set_(["extensions", "io.github.majidkabir.carboncost", "osm_extract"], "2026-11-16"), True),
    ("moved point", set_(["charge_objects", 0, "location", "geometry", "coordinates"], [[1.000001, 2.0]]), True),
    ("another point", set_(["charge_objects", 0, "location", "geometry", "coordinates"], [[1.0, 2.0], [1.1, 2.1]]), True),
    ("booth names", set_(["charge_objects", 0, "location", "point_names"], ["A", "A2"]), True),
    ("headings", set_(["charge_objects", 0, "location", "headings"], [12.5]), True),
    ("extract date in method", set_(["dataset", "method"], "Stations placed at OpenStreetMap's toll booths (extract of 2026-11-16); law of 2025-12-18."), True),
    ("law date in method", set_(["dataset", "method"], "Stations placed at OpenStreetMap's toll booths (extract of 2026-11-08); law of 2026-12-18."), False),
    ("price", set_(["charges", 0, "rates", 0, "amount"], 1.3), False),
    ("station name", set_(["charge_objects", 0, "name"], "B"), False),
    ("station gone", set_(["charge_objects"], []), False),
    ("station unplaced", set_(["charge_objects", 0, "location", "geometry", "coordinates"], []), False),
    ("station without location", set_(["charge_objects", 0, "location"], {}), False),
]

FX = "date,ALL\n2026-11-19,90.02\n2026-11-20,89.78\n"
FX_CASES = [
    ("new days", FX + "2026-11-21,89.78\n2026-11-22,89.78\n", True),
    ("nothing new", FX, False),
    ("past rate changed", "date,ALL\n2026-11-19,90.03\n2026-11-20,89.78\n2026-11-21,89.70\n", False),
    ("currency added", "date,ALL,USD\n2026-11-19,90.02,1\n2026-11-20,89.78,1\n2026-11-21,89.70,1\n", False),
    ("day removed", "date,ALL\n2026-11-19,90.02\n", False),
    ("earlier day added", FX + "2026-11-18,90.18\n", False),
    ("not a day", FX + "total,1\n", False),
]

if __name__ == "__main__":
    bad = [(n, want) for n, f, want in CASES if changed(f) != want]
    bad += [("fx " + n, want) for n, b, want in FX_CASES if appended_days(FX, b) != want]
    CASES += FX_CASES
    for n, want in bad:
        print(f"FAIL {n}: want osm_only={want}")
    print(f"{len(CASES) - len(bad)}/{len(CASES)} ok")
    sys.exit(1 if bad else 0)
