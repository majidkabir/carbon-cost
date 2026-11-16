#!/usr/bin/env python3
"""Checks that the conversion (convert.py) kept every price of the tables.

Usage: check_lossless.py <tables dir> <converted dir>

For each source table it looks up every priced value (rate rows, entry-exit
prices, toll points, sections, zone and fuel charges) in the ORCT file, by
the object, vehicle group and amount it should have there, and reports any
it can't find. It does not reuse the converter's code. Exit 1 on any miss.
"""
import json
import os
import sys
from decimal import Decimal

EXT = "io.github.majidkabir.carboncost"


def D(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(str(x))


def rows_of(ch):
    return [dict(zip(ch["columns"], r)) for r in ch["rows"]]


def check(t, d):
    misses = []
    charges = {c["id"]: c for c in d["charges"]}
    classes = {c["id"]: c for s in d["vehicle_class_sets"] for c in s["classes"]}
    objects = {o["id"]: o for o in d["charge_objects"]}

    # Rate rows: same component charge, a row with an equal amount.
    for r in t.get("rows", []):
        ch = charges.get(r["component"])
        if not ch or not any(D(x["amount"]) == D(r["rate"]) for x in rows_of(ch)):
            misses.append(f"row {r['component']} {r['rate']}")

    # Closed systems: entry and exit names, group label, payment and time variant, amount.
    odd = d.get("extensions", {}).get(EXT, {}).get("closed_system_prices_not_mapped", {})
    for i, s in enumerate(t.get("closed_systems", []), 1):
        ch = charges.get(f"system{i}")
        have = set()
        for x in rows_of(ch) if ch else []:
            if x.get("entry") is None:
                continue
            label = classes[x["vehicle_class"]].get("label")
            variant = "etc" if x.get("user_class") else ("night" if x.get("time_class") else "")
            have.add((objects[x["entry"]]["name"], objects[x["exit"]]["name"], label, variant, D(x["amount"])))
        for variant, table in (("", s["prices"]), ("etc", s.get("etc_prices") or {}), ("night", s.get("night_prices") or {})):
            for key, groups in table.items():
                a, b = key.split("|")
                for g, price in groups.items():
                    if (a, b, g, variant, D(price)) not in have and g not in odd.get(s["name"], {}).get(key, {}):
                        misses.append(f"system {s['name']} {key} {g} {variant} {price}")

    # Toll points: the j-th point at the same place, with each of its amounts.
    point_rows = {}
    for ch in d["charges"]:
        if ch["type"] == "point":
            for x in rows_of(ch):
                point_rows.setdefault(x["object"], set()).add(D(x["amount"]))
    for j, p in enumerate(t.get("toll_points", []), 1):
        o = objects.get(f"pt{j}")
        if not o or o["location"]["geometry"]["coordinates"] != [p["lon"], p["lat"]]:
            misses.append(f"point {j} {p['name']} not placed")
            continue
        want = [p["rate"]] if not p.get("classes") and not p.get("schedule") else []
        want += [c[k] for c in p.get("classes", []) for k in ("rate", "etc_rate", "high_rate", "high_etc_rate", "night_rate",
                                                              "night_etc_rate") if c.get(k)]
        want += [p["peak_rate"]] if p.get("peak_rate") and not p.get("classes") else []
        sched = (t.get("congestion") or {}).get("schedules", {}).get(p.get("schedule"), [])
        want += [ta["amount"] for ta in sched] + [ta["high"] for ta in sched if ta.get("high")]
        misses += [f"point {j} amount {w}" for w in want if D(w) not in point_rows.get(f"pt{j}", set())]
    caps = {D(r["params"]["amount"]) for r in d.get("rules", []) if r["kind"] == "cap"}
    cong = t.get("congestion") or {}
    misses += [f"congestion {k} {cong[k]}" for k in ("day_cap", "day_cap_high") if cong.get(k) and D(cong[k]) not in caps]

    # Sections: every tariff value and every Slovenian class value on its section.
    sec_rows = {}
    for ch in d["charges"]:
        if ch["type"] == "section" and ch["unit"] == "use":
            for x in rows_of(ch):
                sec_rows.setdefault(x["object"], set()).add(D(x["amount"]))
    for s in (t.get("sections") or {}).get("list", []):
        vals = [v for cols in (s.get("tariff") or {}).values() for v in cols]
        vals += [v for cols in (s.get("classes") or {}).values() for v in cols]
        vals += list((s.get("night_kat4") or {}).values())
        misses += [f"section {s['id']} {v}" for v in vals if D(v) not in sec_rows.get("sec:" + s["id"], set())]
    for pk in (t.get("sections") or {}).get("per_km", []):
        ch = charges.get("km-" + pk["component"])
        got = {D(x["amount"]) for x in rows_of(ch)} if ch else set()
        misses += [f"per-km {pk['component']} {k}" for k, v in pk["rates"].items() if D(v) not in got]

    # Zones and fuel.
    if "charge" in t:
        got = {D(x["amount"]) for x in rows_of(charges["zone-charge"])}
        want = [t["charge"]] + [e["charge"] for e in t.get("euro_charges", [])] + ([0] if t.get("exempt_euro") else [])
        misses += [f"zone {w}" for w in want if D(w) not in got]
    if "rate_per_t" in t:
        if D(rows_of(charges["fuel-co2"])[0]["amount"]) != D(t["rate_per_t"]):
            misses.append("fuel rate")
    return misses


def main():
    data, out = sys.argv[1:]
    bad = 0
    for name in sorted(os.listdir(data)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(data, name)) as fh:
            t = json.load(fh)
        with open(os.path.join(out, t["country"].lower(), name[:-5] + ".orct.json")) as fh:
            d = json.load(fh)
        misses = check(t, d)
        if misses:
            bad += 1
            print(f"{name}: {len(misses)} missing, e.g. {misses[:3]}")
    print(f"{bad} tables with missing prices")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
