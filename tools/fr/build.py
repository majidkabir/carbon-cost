"""Builds the French rate table from pairs.csv (parse.py), stations.json
(stations.py) and the fetch manifest.

Usage: python3 build.py pairs.csv stations.json manifest.json fr.json

All documents' pairs go in one chained toll system (rates.TollSystem
with chain): along the route, a truck pays for the published entry-exit
pairs, one after another, that together cover the most of the route
(cost.chainUses). Prices exclude 20% VAT. Where
two documents publish the same pair, the first in documents.json
counts. Rows to or from "Système Ouvert" (the open sections) aren't used.
"""
import csv, json, math, sys

VAT = 1.20


def main(pairs_path, stations_path, manifest_path, out):
    stations = json.load(open(stations_path, encoding="utf-8"))
    prices, docs, conflicts, skipped, by_euro = {}, {}, 0, 0, False
    for r in csv.DictReader(open(pairs_path, encoding="utf-8")):
        docs.setdefault(r["url"], r)
        if r.get("url4"):
            docs.setdefault(r["url4"], dict(r, sha256=r["sha256_4"]))
        if "Système Ouvert" in (r["entry"], r["exit"]):
            skipped += 1
            continue
        k = r["entry"] + "|" + r["exit"]
        p = {"3": round(float(r["class3"]) / VAT, 4), "4": round(float(r["class4"]) / VAT, 4)}
        if r.get("by_euro"):
            p.update({g: round(v / VAT, 4) for g, v in json.loads(r["by_euro"]).items()})
            by_euro = True
        if k in prices:
            conflicts += prices[k] != p
            continue
        prices[k] = p
    names = sorted({n for k in prices for n in k.split("|")})
    st = [{"name": n, "points": [{"name": p["gare"], "lat": p["lat"], "lon": p["lon"]} for p in stations[n]]} for n in names if n in stations]
    valid_from = max(d["valid_from"] for d in docs.values())
    ops = sorted({d["operator"] for d in docs.values()})
    system = {
        "name": "French motorways (" + ", ".join(ops) + ")",
        "law": "Operators' published tariffs (TTC, here excluding 20% VAT) under their concession contracts and the arrêtés of 28 January 2026; vehicle classes 3 (two axles) and 4 (three or more axles), over 3.5 t",
        "chain": True,
        # Operators pricing by EURO class have their own groups; for the
        # others' pairs these fall back on classes 3 and 4.
        "groups": ([{"name": f"{ax} EURO {e}", "min_kg": 3501, **lim, "euro": [e], "base": base}
                    for ax, lim, base in (("2 axles", {"max_axles": 2}, "3"), ("3 axles", {"min_axles": 3, "max_axles": 3}, "4"), ("4+ axles", {"min_axles": 4}, "4"))
                    for e in range(7)] if by_euro else [])
                  + [{"name": "3", "min_kg": 3501, "max_axles": 2}, {"name": "4", "min_kg": 3501, "min_axles": 3}],
        "stations": st,
        "prices": prices,
    }
    t = {
        "country": "FR", "currency": "EUR", "valid_from": valid_from, "valid_to": "2027-01-31",
        "name": "French motorway tolls",
        "law": "Code de la voirie routière art. L122-4 and décret n° 95-81; tariffs set yearly by the concession contracts and the arrêtés of 28 January 2026 relatifs aux péages applicables sur les réseaux autoroutiers concédés, as published by each operator (" + ", ".join(ops) + "). A trip pays the published entry-exit prices along its route, excluding 20% VAT. Stations placed with the ministry's toll station dataset (data.gouv.fr) and OpenStreetMap.",
        "sources": [{"title": f"{d['operator']} tariffs from {d['valid_from']} (sha256 {d['sha256'][:12]})", "url": u} for u, d in docs.items()]
                   + [{"title": "Ministère de la Transition écologique: Gares de péage du réseau routier national concédé", "url": "https://www.data.gouv.fr/datasets/gares-de-peage-du-reseau-routier-national-concede"}],
        "vehicles": "Vehicles over 3.5 t (classes 3 and 4)", "min_kg": 3501,
        "tolled_roads": "The conceded motorways of " + ", ".join(ops) + ". Not included yet: Arcos (A355).",
        "closed_systems": [system],
    }
    json.dump(t, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
    # A check on the stations' places: a pair's stations can't be much
    # further apart than its price pays for (class 3 costs well over
    # 5 cents a km including VAT).
    far = []
    for k, p in prices.items():
        a, b = k.split("|")
        if a in stations and b in stations:
            pa, pb = stations[a][0], stations[b][0]
            km = math.hypot((pa["lat"] - pb["lat"]) * 111, (pa["lon"] - pb["lon"]) * 111 * math.cos(math.radians(pa["lat"])))
            if km > p["3"] * VAT / 0.05 + 40:
                far.append(f"{k}: {km:.0f} km for {p['3'] * VAT:.2f} EUR")
    print(f"{len(far)} pairs whose stations are further apart than their price allows" + "".join("\n  " + f for f in far[:20]))
    print(f"{len(prices)} pairs ({conflicts} conflicting duplicates, {skipped} open-system rows left out), {len(st)} of {len(names)} stations placed, valid from {valid_from}")


if __name__ == "__main__":
    main(*sys.argv[1:])
