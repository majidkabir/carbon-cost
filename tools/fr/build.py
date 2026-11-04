"""Builds the French rate table from pairs.csv (parse.py), stations.json
(stations.py) and the fetch manifest.

Usage: python3 build.py pairs.csv stations.json manifest.json fr.json

All documents' pairs go in one chained toll system (rates.TollSystem
with chain): along the route, a truck pays for the longest published
entry-exit pair from the first station it passes, then again from the
next station after that exit, and so on. Prices exclude 20% VAT. Where
two documents publish the same pair, the first in documents.json
counts. Rows to or from "Système Ouvert" (the open sections) aren't used.
"""
import csv, json, sys

VAT = 1.20


def main(pairs_path, stations_path, manifest_path, out):
    stations = json.load(open(stations_path, encoding="utf-8"))
    prices, docs, conflicts, skipped = {}, {}, 0, 0
    for r in csv.DictReader(open(pairs_path, encoding="utf-8")):
        docs.setdefault(r["url"], r)
        if "Système Ouvert" in (r["entry"], r["exit"]):
            skipped += 1
            continue
        k = r["entry"] + "|" + r["exit"]
        p = {"3": round(float(r["class3"]) / VAT, 4), "4": round(float(r["class4"]) / VAT, 4)}
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
        "groups": [{"name": "3", "min_kg": 3501, "max_axles": 2}, {"name": "4", "min_kg": 3501, "min_axles": 3}],
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
        "tolled_roads": "The conceded motorways of " + ", ".join(ops) + ". Other operators (VINCI Autoroutes, Sanef, SAPN and the smaller concessions) aren't included yet.",
        "closed_systems": [system],
    }
    json.dump(t, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(prices)} pairs ({conflicts} conflicting duplicates, {skipped} open-system rows left out), {len(st)} of {len(names)} stations placed, valid from {valid_from}")


if __name__ == "__main__":
    main(*sys.argv[1:])
