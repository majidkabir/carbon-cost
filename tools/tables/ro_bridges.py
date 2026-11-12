"""Builds Romania's Danube bridge tolls (tarif de trecere, OG 15/2002
art. 1 and Anexa nr. 3): the A2 bridges between Fetești and Cernavodă and
the DN2A bridge between Giurgeni and Vadu Oii, per crossing either way,
from 8 September 2025 (OG 23/2025) until OG 15/2002 was repealed and
TollRo started (30 September 2026).

Usage: python3 ro_bridges.py fetched/ out-dir -> out-dir/ro-danube-bridges-<date>.json

Prices: CNAIR's table of the tariffs under OG 23/2025 (fetch.py's
ro-cnair-peaj-2025.txt, pdftotext -layout), one crossing, lei including
21% VAT (divided out): category 2 (over 3.5 to under 12 t), 3 (12 t and
over, up to 3 axles), 4 (12 t and over, 4 axles or more). Positions: the
middle of the Danube bridge each charges for, from OpenStreetMap
(ro-bridges-osm.json): the A2 bridge at Cernavodă (the Borcea bridge at
Fetești is on the same ticket) and the DN2A bridge at Giurgeni. The
Giurgiu–Ruse bridge (DN5, charged towards Ruse only) isn't in CNAIR's
table and isn't priced.
"""
import json, math, os, re, sys

VAT = 1.21


def km(a, b):
    return math.hypot((a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 111.2)


def middle(g):
    pts = [(p["lat"], p["lon"]) for p in g]
    total = sum(km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    run = 0
    for i in range(len(pts) - 1):
        d = km(pts[i], pts[i + 1])
        if run + d >= total / 2:
            f = (total / 2 - run) / d if d else 0
            return round(pts[i][0] + f * (pts[i + 1][0] - pts[i][0]), 6), round(pts[i][1] + f * (pts[i + 1][1] - pts[i][1]), 6), total
        run += d


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def main(fetched, out):
    tp, op = os.path.join(fetched, "ro-cnair-peaj-2025.txt"), os.path.join(fetched, "ro-bridges-osm.json")
    if not os.path.exists(tp) or not os.path.exists(op):
        print("Romanian Danube bridges: a source wasn't fetched; not built")
        return
    t = open(tp, encoding="utf-8").read()
    i2 = t.find("2. Nivelul tarifelor de trecere pentru utilizarea podurilor peste Dunăre între Fetești")
    i3 = t.find("3. Nivelul tarifelor de trecere pentru utilizarea podului peste Dunăre între Giurgeni")
    if i2 < 0 or i3 < 0 or "(cu TVA" not in t[i2:i3]:
        sys.exit("CNAIR table: bridge sections not found")
    # One crossing: the price followed by "1" passes (Fetești: one per
    # category; Giurgeni: one per sub-category a and b, then category 4).
    fe = [num(v) for v in re.findall(r"([\d.]+,\d\d)\s+1\b", t[i2:i3])]
    gi = [num(v) for v in re.findall(r"([\d.]+,\d\d)\s+1\b", t[i3:])]
    if len(fe) != 4 or len(gi) != 7 or gi[2] != gi[3] or gi[4] != gi[5]:
        sys.exit(f"CNAIR table: unexpected prices {fe} {gi}")
    prices = {"Fetești–Cernavodă": fe[1:4], "Giurgeni–Vadu Oii": [gi[3], gi[5], gi[6]]}
    d = json.load(open(op))
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    longest = {}
    for e in d["elements"]:
        if e["type"] != "way":
            continue
        tags = e.get("tags", {})
        lat, lon, length = middle(e["geometry"])
        key = "Fetești–Cernavodă" if tags.get("ref") == "A2" else "Giurgeni–Vadu Oii"
        if key == "Fetești–Cernavodă" and lon < 28.0:
            continue  # the Borcea bridge at Fetești: same ticket
        if length > longest.get((key, tags.get("oneway")), (0,))[0]:
            longest[(key, tags.get("oneway"))] = (length, lat, lon)
    pts = []
    for (key, _), (length, lat, lon) in sorted(longest.items()):
        if length < 0.8:
            sys.exit(f"{key}: the bridge way is only {length:.2f} km")
        p = prices[key]
        pts.append({"name": f"Danube bridge {key}", "lat": lat, "lon": lon, "rate": 0, "classes": [
            {"min_kg": 3501, "max_kg": 11999, "rate": round(p[0] / VAT, 4)},
            {"min_kg": 12000, "max_axles": 3, "rate": round(p[1] / VAT, 4)},
            {"min_kg": 12000, "min_axles": 4, "rate": round(p[2] / VAT, 4)}]})
    if {p["name"] for p in pts} != {"Danube bridge Fetești–Cernavodă", "Danube bridge Giurgeni–Vadu Oii"}:
        sys.exit(f"bridges not found in OpenStreetMap: {[p['name'] for p in pts]}")
    tb = {"country": "RO", "currency": "RON", "valid_from": "2025-09-08", "valid_to": "2026-09-30", "crossings": True, "osm_extract": stamp,
          "name": "Romania's Danube bridge tolls (tarif de trecere)",
          "law": "Ordonanța Guvernului nr. 15/2002, art. 1 and Anexa nr. 3 (A2 bridges between Fetești and Cernavodă; DN2A bridge between Giurgeni and Vadu Oii), tariffs from 8 September 2025 (OG nr. 23/2025) as CNAIR publishes them: one crossing either way, category 2 (over 3.5 to under 12 t), 3 (12 t and over, up to 3 axles), 4 (4 axles or more), lei excluding 21% VAT. OG 15/2002 was repealed when TollRo started on 1 October 2026. The Giurgiu–Ruse bridge (towards Ruse only) isn't priced.",
          "sources": [{"title": "CNAIR: Tabele ROVINIETA PEAJ (OG 23/2025), the Internet Archive's copy", "url": "https://www.cnadnr.ro/sites/default/files/comunicate-de-presa/Tabele%20ROVINIETA%20PEAJ%20_0.pdf"}],
          "vehicles": "Trucks over 3.5 t, by mass and axles", "min_kg": 3501,
          "tolled_roads": "The A2 Danube bridge at Cernavodă (with the Borcea bridge at Fetești, one ticket) and the DN2A Danube bridge at Giurgeni.",
          "point_match_km": 0.15, "toll_points": pts, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ro-danube-bridges-{tb['valid_from']}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, prices)


if __name__ == "__main__":
    main(*sys.argv[1:])
