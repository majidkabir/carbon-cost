"""Tests of publish.osm_only, publish.appended_days and publish.editions_added: python3 tools/orct/test_publish.py"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish import appended_days, editions_added, osm_only  # noqa: E402

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
    ("point becomes a zone", set_(["charge_objects", 0, "location", "geometry"], {"type": "MultiPolygon", "coordinates": [[[[1, 2], [1, 3], [2, 3], [1, 2]]]]}), False),
    ("another date after OpenStreetMap", set_(["dataset", "method"], "Stations placed at OpenStreetMap's toll booths (extract of 2026-11-08); law of 2025-12-18, in force 2026-01-01."), False),
]

# Pairs whose committed side isn't BASE: (name, committed, new, want).
UNPLACED = copy.deepcopy(BASE)
UNPLACED["charge_objects"][0]["location"]["geometry"]["coordinates"] = []
UNDATED = copy.deepcopy(BASE)
UNDATED["dataset"]["method"] = "Stations at OpenStreetMap's toll booths, as the law in force from 2026-01-01 lists them."
PAIRS = [
    ("station placed", UNPLACED, BASE, False),
    ("law date after an undated OpenStreetMap", UNDATED,
     dict(UNDATED, dataset={**UNDATED["dataset"], "method": UNDATED["dataset"]["method"].replace("2026-01-01", "2026-02-01")}), False),
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

ETS = {"note": "n", "operators": [{"operator": "Stena Line", "unit": "EUR per lane metre", "source": {"url": "u"}, "routes": [],
        "editions": [{"from": "2026-11-01", "to": "2026-11-30", "source": "u (read in Chrome)", "rates": {"Trelleborg–Rostock": 1.59}}]}]}


def ets(f):
    b = json.loads(json.dumps(ETS))
    f(b["operators"][0])
    return b


ETS_CASES = [
    ("month added", ets(lambda o: o["editions"].append({"from": "2026-12-01", "to": "2026-12-31", "source": "u", "rates": {"Trelleborg–Rostock": 1.7}})), True),
    ("fetched instead of read", ets(lambda o: o["editions"][0].update(source="u (eu-ets-november-2026-11.pdf)")), True),
    ("earlier month added", ets(lambda o: o["editions"].insert(0, {"from": "2026-10-01", "to": "2026-10-31", "source": "u", "rates": {"Trelleborg–Rostock": 1.5}})), True),
    ("rate changed", ets(lambda o: o["editions"][0]["rates"].update({"Trelleborg–Rostock": 1.6})), False),
    ("month gone", ets(lambda o: o.update(editions=[])), False),
    ("unit changed", ets(lambda o: o.update(unit="EUR per metre")), False),
]

# Scandlines: the latest edition is open (no "to") until the next notice.
OPEN = json.loads(json.dumps(ETS))
del OPEN["operators"][0]["editions"][0]["to"]


def opened(f):
    b = json.loads(json.dumps(OPEN))
    f(b["operators"][0]["editions"])
    return b


def next_month(eds):
    eds[0]["to"] = "2026-11-30"
    eds.append({"from": "2026-12-01", "source": "u", "rates": {"Trelleborg–Rostock": 1.7}})


def ended_early(eds):
    eds[0]["to"] = "2026-11-20"
    eds.append({"from": "2026-12-01", "source": "u", "rates": {"Trelleborg–Rostock": 1.7}})


OPEN_CASES = [
    ("open edition ends as the next starts", opened(next_month), True),
    ("open edition ends with no next", opened(lambda e: e[0].update(to="2026-11-30")), False),
    ("open edition ends early", opened(ended_early), False),
]

if __name__ == "__main__":
    bad = [(n, want) for n, f, want in CASES if changed(f) != want]
    bad += [(n, want) for n, a, b, want in PAIRS if osm_only(a, b) != want]
    bad += [("fx " + n, want) for n, b, want in FX_CASES if appended_days(FX, b) != want]
    bad += [("ets " + n, want) for n, b, want in ETS_CASES if editions_added(ETS, b) != want]
    bad += [("ets " + n, want) for n, b, want in OPEN_CASES if editions_added(OPEN, b) != want]
    CASES += PAIRS + FX_CASES + ETS_CASES + OPEN_CASES
    for n, want in bad:
        print(f"FAIL {n}: want osm_only={want}")
    print(f"{len(CASES) - len(bad)}/{len(CASES)} ok")
    sys.exit(1 if bad else 0)
