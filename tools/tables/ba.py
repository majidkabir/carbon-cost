"""Builds the A1 motorway tolls of the Federation of Bosnia and Herzegovina
from the Government's decree (Uredba o izmjeni Uredbe o naplati naknade za
korištenje autoceste A1, Službene novine FBiH 86/20, fetch.py's
ba-uredba-86-20.txt), the article 3 it sets out: per direction (pravac),
from each toll station (naplatno mjesto) to each other, by vehicle class
I-IV, in KM with VAT.

Usage: python3 ba.py fetched/ out-dir -> out-dir/ba-<date>.json

- Directions with entry and exit stations (Sarajevo–Zenica and back,
  Sarajevo–Tarčin and back) are closed systems, priced by direction.
- A section with a single mainline station (čeono naplatno mjesto, ČNM:
  Svilaj, Ljubuški) charges its price per passage there, either way.
- Classes (Pravilnik SN 53/15, article 6, as JP Autoceste FBiH's price
  list page gives them): III two or three axles, IV four or more, both
  over 1.3 m at the first axle; trucks over 3.5 t are taken to be.
- Prices exclude 17% VAT (PDV) and are converted to euros at the fixed
  rate of the convertible mark, 1 EUR = 1.95583 KM (Zakon o Centralnoj
  banci Bosne i Hercegovine, article 32).
- Stations: OSM toll booths named "Naplatna postaja <name>" of JP
  Autoceste FBiH (fetch.py's ba-osm.json).

The A1 sections opened after the decree (stations such as Golubinja,
Bradina, Čapljina) are tolled under acts not found; they are not priced.
"""
import json, math, os, re, sys, unicodedata

VAT = 1.17
KM_PER_EUR = 1.95583


def plain(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s-]+", " ", s).strip().lower()


def num(s):
    return float(s.replace(",", "."))


def title(s):
    return " ".join(w if w in ("I", "II") else w.capitalize() for w in s.split())


def parse(text):
    """{direction: (flat, {(from, to): (km, III, IV)})}; flat when the
    direction is one mainline station: {(name, name): ...}."""
    text = text.replace("\f", "\n")
    parts = re.split(r"^\s*([a-f])\) Pravac:? (.+?)\s*$", text, flags=re.M)
    out = {}
    for i in range(1, len(parts) - 2, 3):
        name, body = parts[i + 1].replace("–", "-").strip(), parts[i + 2]
        pairs, src = {}, None
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        for j, l in enumerate(lines):
            m = re.match(r"^(ČNM|BNM) ([A-ZČĆŽŠĐ ]+?)(?:\s+km\s+I\s+II\s+III\s+IV)?$", l)
            if m and m.group(2).isupper():
                src = title(m.group(2))
                # A mainline station with its single price on the next line.
                if j + 1 < len(lines) and (f := re.match(r"^([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)$", lines[j + 1])):
                    pairs[(src, src)] = (num(f.group(1)), num(f.group(4)), num(f.group(5)))
                continue
            r = re.match(r"^(ČNM|BNM) (.+?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)$", l)
            if r and src:
                pairs[(src, r.group(2).strip())] = (num(r.group(3)), num(r.group(6)), num(r.group(7)))
        out[name] = pairs
    # One spelling per station: the rows' (headers are in capitals).
    spell = {}
    for pairs in out.values():
        for (f, t) in pairs:
            spell.setdefault(plain(t), t)
    for pairs in out.values():
        for (f, t), v in list(pairs.items()):
            del pairs[(f, t)]
            pairs[(spell.get(plain(f), f), spell.get(plain(t), t))] = v
    return out


def main(fetched, out):
    text = open(os.path.join(fetched, "ba-uredba-86-20.txt"), encoding="utf-8").read()
    if "86/20" not in text or "Klasa vozila i cijena u KM sa PDV-om" not in text:
        sys.exit("Bosnia: the decree text changed")
    day = re.search(r"održanoj (\d\d)\.(\d\d)\.(\d{4})", text)
    dirs = parse(text)
    want = {"Svilaj - Odžak", "Sarajevo - Zenica", "Zenica - Sarajevo", "Sarajevo - Tarčin", "Tarčin - Sarajevo", "Međugorje - Ljubuški"}
    if set(dirs) != want or not day:
        sys.exit(f"Bosnia: directions {sorted(dirs)}")
    n = sum(len(p) for p in dirs.values())
    if n != 58:
        sys.exit(f"Bosnia: {n} prices read")

    d = json.load(open(os.path.join(fetched, "ba-osm.json")))
    booths = {}
    for e in d["elements"]:
        tg = e.get("tags", {})
        if e["type"] == "node" and tg.get("barrier") == "toll_booth" and tg.get("operator") == "JP Autoceste FBiH":
            m = re.match(r"^Naplatna postaja (.+)$", tg.get("name", ""), re.I)
            if m:
                booths.setdefault(plain(m.group(1)), []).append((e["lat"], e["lon"]))

    def place(name):
        bs = booths.get(plain(name))
        if not bs:
            sys.exit(f"Bosnia: no OSM toll booth for {name}")
        return [{"name": "booth", "lat": round(a, 6), "lon": round(b, 6)} for a, b in bs]

    eur = lambda km: round(km / VAT / KM_PER_EUR, 4)
    groups = [{"name": "III", "min_kg": 3501, "max_axles": 3}, {"name": "IV", "min_kg": 3501, "min_axles": 4}]
    closed, points = [], []
    for a, b in (("Sarajevo - Zenica", "Zenica - Sarajevo"), ("Sarajevo - Tarčin", "Tarčin - Sarajevo")):
        prices, names = {}, set()
        for direction in (a, b):
            for (f, t), (_, c3, c4) in dirs[direction].items():
                names |= {f, t}
                prices[f"{f}|{t}"] = {"III": eur(c3), "IV": eur(c4)}
        closed.append({"name": "A1 " + a.replace(" - ", "–"), "law": f"Uredba SN 86/20, article 3, directions {a} and {b}.",
                       "directed": True, "groups": groups, "stations": [{"name": s, "points": place(s)} for s in sorted(names)], "prices": prices})
    for direction in ("Svilaj - Odžak", "Međugorje - Ljubuški"):
        ((f, _), (_, c3, c4)), = dirs[direction].items()
        for p in place(f):
            points.append({"name": f"A1 {direction.replace(' - ', '–')}: {f}", "lat": p["lat"], "lon": p["lon"], "rate": 0,
                           "classes": [{"min_kg": 3501, "max_axles": 3, "rate": eur(c3)}, {"min_kg": 3501, "min_axles": 4, "rate": eur(c4)}]})
    vf = f"{day.group(3)}-{day.group(2)}-{day.group(1)}"
    tb = {
        "country": "BA", "currency": "EUR", "valid_from": vf, "crossings": True,
        "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
        "name": "A1 motorway tolls (Federation of Bosnia and Herzegovina)",
        "law": ("Uredba o naplati naknade za korištenje autoceste A1 (Službene novine FBiH 54/15) article 3 as replaced by the Uredba of 26 November 2020 (86/20), in force the day after publication: "
                "per direction from each toll station to each other on Svilaj–Odžak, Sarajevo–Zenica, Sarajevo–Tarčin and Međugorje–Ljubuški, class III (two or three axles) and IV (four or more), "
                "excluding 17% VAT, converted at the convertible mark's fixed 1.95583 KM per euro. The A1 sections opened since (e.g. at Golubinja, Bradina, Čapljina) aren't priced: the act setting their tolls wasn't found."),
        "sources": [{"title": "Uredba o izmjeni Uredbe o naplati naknade za korištenje autoceste A1 (SN 86/20), on JP Autoceste FBiH's site", "url": "http://jpautoceste.ba/wp-content/uploads/2020/11/Uredba-o-izmjeni-Uredbe-o-naplati-naknade-za-kori%C5%A1tenje-autoceste-A1-SN-86-20-1.pdf"},
                    {"title": "JP Autoceste FBiH: Pricelist and vehicle category", "url": "https://www.jpautoceste.ba/en/pricelist/"},
                    {"title": "Zakon o Centralnoj banci Bosne i Hercegovine, article 32 (1 EUR = 1.95583 KM)", "url": "https://www.cbbh.ba/content/read/915"},
                    {"title": "OpenStreetMap (Overpass API): JP Autoceste FBiH's toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Classes III and IV (over 1.3 m at the first axle; here trucks over 3.5 t)", "min_kg": 3501,
        "tolled_roads": "A1 Svilaj–Odžak, Sarajevo sjever–Zenica sjever, Sarajevo zapad–Tarčin, Međugorje–Ljubuški.",
        "point_match_km": 0.2,
        "toll_points": points,
        "closed_systems": closed,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ba-{vf}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, sum(len(c["prices"]) for c in closed), "prices,", len(points), "mainline points")


if __name__ == "__main__":
    main(*sys.argv[1:])
