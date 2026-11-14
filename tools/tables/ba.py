"""Builds the A1 motorway tolls of the Federation of Bosnia and Herzegovina
one table per act: the Government's decree SN 86/20 (to 21 August 2024),
its replacement SN 63/24 (from 22 August 2024) and JP Autoceste FBiH's
price list from 1 November 2026 (up to 15% higher, as article 6 of the
2024 decree allows); fetch.py's ba-uredba-86-20.txt, ba-uredba-63-24.txt
and ba-cjenovnik-2026-11.txt. Each sets out, per direction (pravac), the
price from each toll station (naplatno mjesto) to each other, by vehicle
class, in KM with VAT.

Usage: python3 ba.py fetched/ out-dir -> out-dir/ba-<date>.json

- Directions with entry and exit stations are directed closed systems,
  a direction and its reverse together.
- A section with a single mainline station (čeono naplatno mjesto, ČNM,
  e.g. Svilaj) charges its price per passage there, either way.
- Classes (Pravilnik SN 53/15, article 6, as JP Autoceste FBiH's price
  list page gives them): III two or three axles, IV four or more, both
  over 1.3 m at the first axle; trucks over 3.5 t are taken to be.
- Prices exclude 17% VAT (PDV) and are converted to euros at the fixed
  rate of the convertible mark, 1 EUR = 1.95583 KM (Zakon o Centralnoj
  banci Bosne i Hercegovine, article 32).
- Stations: OSM toll booths named "Naplatna postaja <name>" of JP
  Autoceste FBiH (fetch.py's ba-osm.json).

Stations with no OSM booth of that name (e.g. Žepče, Tešanj, Usora) are
left out, with their prices, and named in the table's law.
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
    """"SARAJEVO SJEVER", "Sarajevo Sjever" -> "Sarajevo sjever"; "KAKANJ II" -> "Kakanj II"."""
    ws = s.split()
    return " ".join(w if w in ("I", "II") else (w.capitalize() if i == 0 else w.lower()) for i, w in enumerate(ws))


def parse(text):
    """{direction: {(from, to): (km, III, IV)}}; a single mainline station
    with one price is (name, name)."""
    text = text.replace("\f", "\n").replace("–", "-")
    parts = re.split(r"^\s*([a-z])\)\s*Pravac:?\s*(.+?)\s*$", text, flags=re.M)
    out = {}
    nums = r"((?:\s+\d+\.\d+){4,5})"
    for i in range(1, len(parts) - 2, 3):
        name = re.sub(r"\s*-\s*", " - ", parts[i + 1].strip())
        pairs, src = {}, None
        lines = [l.strip() for l in parts[i + 2].split("\n") if l.strip()]
        for j, l in enumerate(lines):
            m = re.match(r"^(ČNM|BNM) ([A-Za-zČĆŽŠĐčćžšđ ]+?)(\s+km\s+(?:Ia\s+)?I\s+II\s+III\s+IV)?$", l)
            if m and (m.group(3) or m.group(2).isupper()):
                src = m.group(2).strip()
                if not m.group(3) and j + 1 < len(lines) and (f := re.match(r"^(\d+\.\d+)" + nums + "$", lines[j + 1])):
                    p = f.group(2).split()
                    pairs[(src, src)] = (num(f.group(1)), num(p[-2]), num(p[-1]))
                continue
            r = re.match(r"^(ČNM|BNM) (.+?)\s+(\d+\.\d+)" + nums + r"(?:\s{3,}.*)?$", l)
            if r and src:
                p = r.group(4).split()
                pairs[(src, r.group(2).strip())] = (num(r.group(3)), num(p[-2]), num(p[-1]))
        out[name] = pairs
    # One spelling per station.
    for pairs in out.values():
        for (f, t), v in list(pairs.items()):
            del pairs[(f, t)]
            pairs[(title(f), title(t))] = v
    return out


DOCS = [
    # (fetched file, valid_from, valid_to, expected prices, title, url, law)
    ("ba-uredba-86-20.txt", "2020-11-26", "2024-08-21", 58,
     "Uredba o izmjeni Uredbe o naplati naknade za korištenje autoceste A1 (SN 86/20), on JP Autoceste FBiH's site",
     "http://jpautoceste.ba/wp-content/uploads/2020/11/Uredba-o-izmjeni-Uredbe-o-naplati-naknade-za-kori%C5%A1tenje-autoceste-A1-SN-86-20-1.pdf",
     "Uredba o naplati naknade za korištenje autoceste A1 (SN 54/15) article 3 as replaced by the Uredba of 26 November 2020 (SN 86/20, in force the day after publication; valid_from is the day it was adopted)"),
    ("ba-uredba-63-24.txt", "2024-08-22", "2026-10-31", 69,
     "Službene novine FBiH 63/24 (14 August 2024): Uredba o naplati naknade za korištenje autoceste A1, as published by the FBiH legal aid office",
     "http://www.upfbihpravnapomoc.ba/udocs/U41BBCAE_Uredba20o20naplati20naknade20za20koriC5A1tenje20autoceste20A1.pdf",
     "Uredba o naplati naknade za korištenje autoceste A1 (SN 63/24, in force the eighth day after publication on 14 August 2024), article 3"),
    ("ba-cjenovnik-2026-11.txt", "2026-11-01", "", 86,
     "JP Autoceste FBiH: price list from 1 November 2026 (up to 15% over the decree's, under its article 6)",
     "https://www.jpautoceste.ba/wp-content/uploads/2026/11/Cjenovnik-od-1.11.2026.-godine.pdf",
     "JP Autoceste FBiH's price list from 1 November 2026, raised by up to 15% over the prices of the Uredba o naplati naknade za korištenje autoceste A1 (SN 63/24 and 74/26) under its article 6"),
]


def main(fetched, out):
    d = json.load(open(os.path.join(fetched, "ba-osm.json")))
    booths = {}
    for e in d["elements"]:
        tg = e.get("tags", {})
        if e["type"] == "node" and tg.get("barrier") == "toll_booth" and tg.get("operator") == "JP Autoceste FBiH":
            m = re.match(r"^Naplatna postaja (.+)$", tg.get("name", ""), re.I)
            if m:
                booths.setdefault(plain(m.group(1)), []).append((e["lat"], e["lon"]))

    def place(name):
        return [{"name": "booth", "lat": round(a, 6), "lon": round(b, 6)} for a, b in booths.get(plain(name), [])]

    eur = lambda km: round(km / VAT / KM_PER_EUR, 4)
    groups = [{"name": "III", "min_kg": 3501, "max_axles": 3}, {"name": "IV", "min_kg": 3501, "min_axles": 4}]
    for fname, vf, vt, want, stitle, url, law in DOCS:
        path = os.path.join(fetched, fname)
        if not os.path.exists(path):
            print(f"Bosnia: {fname} not fetched; not built")
            continue
        text = open(path, encoding="utf-8").read()
        if not re.search(r"Klasa vozila i cijena u KM sa? PDV-? ?om", text):
            sys.exit(f"Bosnia: {fname} changed")
        dirs = parse(text)
        n = sum(len(p) for p in dirs.values())
        if (want and n != want) or n < 50:
            sys.exit(f"Bosnia: {fname}: {n} prices read")
        missing = sorted({s for p in dirs.values() for pair in p for s in pair if not place(s)})
        closed, points, done = [], [], set()
        for a in dirs:
            if a in done:
                continue
            f, t = a.split(" - ")
            b = f"{t} - {f}"
            flat = list(dirs[a]) == [list(dirs[a])[0]] and list(dirs[a])[0][0] == list(dirs[a])[0][1]
            if flat:
                (st, _), (_, c3, c4) = next(iter(dirs[a].items()))
                for p in place(st):
                    points.append({"name": f"A1 {a.replace(' - ', '–')}: {st}", "lat": p["lat"], "lon": p["lon"], "rate": 0,
                                   "classes": [{"min_kg": 3501, "max_axles": 3, "rate": eur(c3)}, {"min_kg": 3501, "min_axles": 4, "rate": eur(c4)}]})
                done.add(a)
                continue
            prices, names = {}, set()
            for direction in (a, b) if b in dirs else (a,):
                done.add(direction)
                for (x, y), (_, c3, c4) in dirs[direction].items():
                    if x in missing or y in missing:
                        continue
                    names |= {x, y}
                    prices[f"{x}|{y}"] = {"III": eur(c3), "IV": eur(c4)}
            if prices:
                closed.append({"name": "A1 " + a.replace(" - ", "–"), "law": f"{law}: directions {a} and {b}.",
                               "directed": True, "groups": groups, "stations": [{"name": s, "points": place(s)} for s in sorted(names)], "prices": prices})
        if not closed or not points:
            sys.exit(f"Bosnia: {fname}: {len(closed)} closed systems, {len(points)} mainline points")
        tb = {
            "country": "BA", "currency": "EUR", "valid_from": vf, "crossings": True,
            "osm_extract": d.get("osm3s", {}).get("timestamp_osm_base", "")[:10],
            "name": "A1 motorway tolls (Federation of Bosnia and Herzegovina)",
            "law": (law + ": per direction from each toll station to each other, class III (two or three axles) and IV (four or more), excluding 17% VAT, "
                    "converted at the convertible mark's fixed 1.95583 KM per euro. Stations at JP Autoceste FBiH's OSM toll booths"
                    + (f"; not placed, so not priced: {', '.join(missing)}." if missing else ".")),
            "sources": [{"title": stitle, "url": url},
                        {"title": "JP Autoceste FBiH: Pricelist and vehicle category", "url": "https://www.jpautoceste.ba/en/pricelist/"},
                        {"title": "Zakon o Centralnoj banci Bosne i Hercegovine, article 32 (1 EUR = 1.95583 KM)", "url": "https://www.cbbh.ba/content/read/915"},
                        {"title": "OpenStreetMap (Overpass API): JP Autoceste FBiH's toll booths", "url": "https://www.openstreetmap.org/"}],
            "vehicles": "Classes III and IV (over 1.3 m at the first axle; here trucks over 3.5 t)", "min_kg": 3501,
            "tolled_roads": "A1 in the Federation: " + ", ".join(c["name"][3:] for c in closed) + "; mainline barriers: " + ", ".join(sorted({p["name"].split(": ")[1] for p in points})) + ".",
            "point_match_km": 0.2,
            "toll_points": points,
            "closed_systems": closed,
            "rows": [],
        }
        if vt:
            tb["valid_to"] = vt
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"ba-{vf}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, n, "prices read,", sum(len(c["prices"]) for c in closed), "priced,", len(points), "mainline points; not placed:", missing)


if __name__ == "__main__":
    main(*sys.argv[1:])
