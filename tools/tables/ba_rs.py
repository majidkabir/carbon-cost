"""Builds Republika Srpska's motorway tolls (JP "Autoputevi Republike
Srpske": the 9. januar and Gradiška–Banja Luka motorways) as one closed
system priced by entry and exit toll station.

Usage: python3 ba_rs.py fetched/ out-dir -> out-dir/ba-rs-<date>.json

Prices: the operator's price list at each toll station, "on the basis of
the Uredba o visini putarine, article 4(1), Službeni glasnik RS 89/19",
published only as images in PDFs (uploaded 2 October 2024, linked from
https://autoputevirs.com/clanci/cjn/1207); transcribed by hand into
transcribed/ba-rs-<station>.json with each PDF's sha256 (check_transcribed.py
says when one changes). Class III (two or three axles over 1.3 m at the
first axle) and IV (four or more axles, 2.9 m or more); trucks over 3.5 t
are taken to be. KM with 17% VAT, divided out and converted at the
convertible mark's fixed 1.95583 KM per euro.

Stations: the operator's OSM toll booths "Naplatna Postaja <name>"
(fetch.py's rs-ba-osm.json).
"""
import glob, json, os, re, sys, unicodedata

VAT = 1.17
KM_PER_EUR = 1.95583
START = "2024-10-02"  # the price lists' upload date; the Uredba (SG RS 89/19) dates from 2019


def plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().strip()


def main(transcribed, fetched, out):
    sheets = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(transcribed, "ba-rs-*.json")))]
    if len(sheets) != 9:
        sys.exit(f"Republika Srpska: {len(sheets)} transcribed price lists")
    pairs = {}
    for s in sheets:
        for r in s["rows"]:
            pairs[(r["from"], s["exit"])] = (r["III"], r["IV"])
    for (a, b), v in pairs.items():
        if pairs.get((b, a)) != v:
            sys.exit(f"Republika Srpska: {a}-{b} isn't priced the same both ways")
    names = sorted({x for p in pairs for x in p})

    d = json.load(open(os.path.join(fetched, "rs-ba-osm.json")))
    booths = {}
    for e in d["elements"]:
        tg = e.get("tags", {})
        if e["type"] == "node" and tg.get("barrier") == "toll_booth" and tg.get("operator") == "Autoputevi Republike Srpske":
            m = re.match(r"^Naplatna Postaja (.+)$", tg.get("name", ""), re.I)
            if m:
                booths.setdefault(plain(m.group(1)), []).append((e["lat"], e["lon"]))
    missing = [n for n in names if plain(n) not in booths]
    if missing:
        sys.exit(f"Republika Srpska: no OSM toll booth for {missing}")
    eur = lambda km: round(km / VAT / KM_PER_EUR, 4)
    tb = {
        "country": "BA", "currency": "EUR", "valid_from": START, "crossings": True,
        "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
        "name": "Republika Srpska motorway tolls (Autoputevi Republike Srpske)",
        "law": ("Uredba o visini putarine (Službeni glasnik Republike Srpske 89/19), article 4(1), as JP Autoputevi Republike Srpske's price list at each toll station gives it "
                "(published as images, uploaded 2 October 2024, transcribed by hand): by entry and exit station either way, class III (two or three axles) and IV (four or more), "
                "excluding 17% VAT, converted at the convertible mark's fixed 1.95583 KM per euro. valid_from is the price lists' upload date."),
        "sources": [{"title": "Autoputevi Republike Srpske: Cjenovnik (price lists per toll station)", "url": "https://autoputevirs.com/clanci/cjn/1207"},
                    {"title": "The price lists as transcribed in tools/tables/transcribed/ba-rs-*.json", "url": sheets[0]["source"]["url"]},
                    {"title": "Zakon o Centralnoj banci Bosne i Hercegovine, article 32 (1 EUR = 1.95583 KM)", "url": "https://www.cbbh.ba/content/read/915"},
                    {"title": "OpenStreetMap (Overpass API): the operator's toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Classes III and IV (here trucks over 3.5 t)", "min_kg": 3501,
        "tolled_roads": "Motorways 9. januar (Kostajnica–Kladari–Prnjavor–Laktaši) and Gradiška–Banja Luka (Čatrnja–Nova Topola–Aleksandrovac–Jakupovci).",
        "closed_systems": [{
            "name": "Autoputevi Republike Srpske", "law": "Uredba o visini putarine (SG RS 89/19): by entry and exit station.",
            "groups": [{"name": "III", "min_kg": 3501, "max_axles": 3}, {"name": "IV", "min_kg": 3501, "min_axles": 4}],
            "stations": [{"name": n, "points": [{"name": "booth", "lat": round(a, 6), "lon": round(b, 6)} for a, b in booths[plain(n)]]} for n in names],
            "prices": {f"{a}|{b}": {"III": eur(v[0]), "IV": eur(v[1])} for (a, b), v in sorted(pairs.items()) if a < b}}],
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ba-rs-{START}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(tb["closed_systems"][0]["prices"]), "pairs")


if __name__ == "__main__":
    main(*sys.argv[1:])
