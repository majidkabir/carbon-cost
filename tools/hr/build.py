"""Builds rates/data/hr-2026-01-01.json from fetch.py's hr-prices.json and
hr-booths.json (OpenStreetMap toll booths and motorway junctions).

Usage: python3 build.py hr-prices.json hr-booths.json out.json

Bina-Istra's Istrian Y prices come from bina-istra.json (fetch.py, from
its online toll calculator); pass its path as a fourth argument, else the
copy in this folder is used.
"""
import json, math, os, re, sys

VAT = 1.25
SYSTEMS = {
    "a1": "A1, A6, A10 Zagreb – Split – Rijeka – Čarapine",
    "a2": "A2 Zagreb – Macelj",
    "a3": "A3, A5 Zagreb – Lipovac – Osijek – Svilaj",
    "a4": "A4 Zagreb – Goričan",
    "a11": "A11 Zagreb – Sisak",
    "bregana": "A3 Bregana",
    "rupa": "A7 Rupa",
    "bina": "A8, A9 Istrian Y (Bina-Istra)",
}
# Price-list names that differ from OpenStreetMap's.
ALIAS = {
    ("a1", "Zagreb"): "Zagreb - Lučko",
    ("a1", "Rijeka (Grobnik)"): "Rijeka-Grobnik",
    ("a1", "Zdenčina"): "Donja Zdenčina",
    ("a1", "Podi"): "Šibenik - Podi",
    ("a2", "Trakošćan"): "Trakoščan",
    ("a3", "Zagreb istok"): "Zagreb Istok",
    ("a3", "ČCP Svilaj"): "Svilaj",
    ("a3", "Sl. Brod zapad"): "Slavonski Brod - zapad",
    ("a3", "Sl. Brod istok"): "Slavonski Brod - istok",
    ("a4", "Brez. Hum"): "Breznički Hum",
    ("a4", "Varaž. Toplice"): "Varaždinske Toplice",
    ("a2", "Začretje"): "Sveti Križ Začretje",
    ("bina", "Vodnjan Sjever"): "Vodnjan - sjever",
    ("bina", "Vodnjan Jug"): "Vodnjan - jug",
    ("bina", "Nova Vas"): "Novigrad",
    ("bina", "Tunel Učka"): ("Tunel Učka", "Učka (portal Kvarner)"),
}
CANON = {("a4", "Brez. Hum"): "Breznički Hum", ("a4", "Varaž. Toplice"): "Varaždinske Toplice"}


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def key(s):
    s = norm(s).lower()
    for p in ("naplatna postaja ", "np "):
        if s.startswith(p):
            s = s[len(p):]
    return s


def km(a, b):
    return math.hypot((a["lon"] - b["lon"]) * 111.2 * math.cos(math.radians(a["lat"])), (a["lat"] - b["lat"]) * 111.2)


def main(prices_path, booths_path, out, bina_path=None):
    prices = json.load(open(prices_path))
    bina = json.load(open(bina_path or os.path.join(os.path.dirname(__file__), "bina-istra.json")))
    # Merge Bina-Istra's pairs under their entries.
    prices["bina"] = {}
    for k, p in bina["prices"].items():
        a, b = k.split("|")
        prices["bina"].setdefault(a, []).append([b, None, None, None, p["III"], p["IV"]])
    allosm = json.load(open(booths_path))["booths"]
    systems = []
    missing = []
    for page, entries in prices.items():
        # West of about 14.25 E is Istria: Bina-Istra's network, not HAC's (its
        # Novigrad is not the A1's).
        osm = [b for b in allosm if (b["lon"] < 14.26 if page == "bina" else b["lon"] >= 14.22)]
        booths = [b for b in osm if b["kind"] == "toll_booth"]
        juncs = [b for b in osm if b["kind"] == "motorway_junction"]
        canon = lambda n: CANON.get((page, norm(n)), norm(n))
        names = sorted({canon(e) for e in entries} | {canon(r[0]) for rows in entries.values() for r in rows})
        stations = []
        for n in names:
            want = ALIAS.get((page, n), n)
            want = {key(w) for w in (want if isinstance(want, tuple) else (want,))}
            bs = [b for b in booths if key(b["name"]) in want]
            js = [j for j in juncs if key(j["name"]) in want]
            if bs:
                js = [j for j in js if min(km(j, b) for b in bs) <= 3]
            pts = [{"name": "booth" if p in bs else "junction", "lat": round(p["lat"], 5), "lon": round(p["lon"], 5)} for p in bs + js]
            if not pts:
                missing.append((page, n))
            stations.append({"name": n, "points": pts})
        pr = {}
        for e, rows in entries.items():
            for r in rows:
                if r[4] is None or r[5] is None:
                    continue
                pr[canon(e) + "|" + canon(r[0])] = {"III": round(r[4] / VAT, 4), "IV": round(r[5] / VAT, 4)}
        law = "Hrvatske autoceste price list (hac.hr, toll rates " + page + "), EUR including 25% VAT, here excluding it; vehicle groups by Pravilnik o cestarini (NN 130/2013) art. 2"
        discounts = [{"name": "ENC", "etc": True, "percent": 21.74}, {"name": "ENC EURO V/EEV", "etc": True, "euro": [5], "percent": 3}, {"name": "ENC EURO VI", "etc": True, "euro": [6], "percent": 7}]
        if page == "bina":
            law = "Bina-Istra toll price list (bina-istra.com toll calculator), EUR including 25% VAT, here excluding it; vehicle groups by Pravilnik o cestarini (NN 130/2013) art. 2"
            discounts = [{"name": "ENC PLUS", "etc": True, "percent": 30}]
        systems.append({
            "name": SYSTEMS[page],
            "law": law,
            "discounts": discounts,
            "groups": [{"name": "III", "min_kg": 3501, "max_axles": 3}, {"name": "IV", "min_kg": 3501, "min_axles": 4}],
            "stations": stations,
            "prices": pr,
        })
        print(page, len(stations), "stations", len(pr), "prices", sum(len(s["points"]) for s in stations), "points")
    print("no OpenStreetMap point:", missing)
    t = {
        "country": "HR", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
        "name": "Croatian motorway toll (Hrvatske autoceste)",
        "law": "Zakon o cestama and Pravilnik o cestarini (NN 130/2013): toll from entry to exit station on the closed motorway systems, and per passage at the open stations Bregana and Rupa, by vehicle group (III: 2-3 axles over 3.5 t, IV: 4 or more axles). Prices are Hrvatske autoceste's price list (checked 4 November 2026), excluding 25% VAT. They are the full prices; with etc (paying by ENC electronic toll) HAC gives 21.74% off and EURO V/EEV 3% or EURO VI 7% more (taken as added to the 21.74%), and Bina-Istra 30% (ENC PLUS).",
        "sources": [{"title": "Hrvatske autoceste: toll rates", "url": "https://www.hac.hr/en/toll/toll-rates/a1"},
                    {"title": "Hrvatske autoceste: ENC discounts", "url": "https://www.hac.hr/en/toll/etc"},
                    {"title": "Bina-Istra: toll calculator", "url": "https://bina-istra.com/karta/hamburger.html"},
                    {"title": "Pravilnik o cestarini (Narodne novine 130/2013)", "url": "https://narodne-novine.nn.hr/clanci/sluzbeni/2013_10_130_2833.html"}],
        "vehicles": "Vehicles over 3.5 t (groups III and IV)",
        "min_kg": 3501,
        "tolled_roads": "HAC's motorways (A1, A2, A3, A4, A5, A6, A7 Rupa, A10, A11) and Bina-Istra's Istrian Y (A8, A9).",
        "closed_systems": systems,
    }
    json.dump(t, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
