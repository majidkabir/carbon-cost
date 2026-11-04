"""Builds rates/data/rs-2026-07-01.json from JP Putevi Srbije's toll price
list (cene_putarina_lat.pdf, as pdftotext -layout text) and Serbia's
OpenStreetMap toll booths (osmium geojsonseq).

Usage: python3 build.py prices.txt booths.geojsonseq out.json
"""
import json, re, sys
from collections import defaultdict

CYR = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџшАБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ",
               ["a","b","v","g","d","đ","e","ž","z","i","j","k","l","lj","m","n","nj","o","p","r","s","t","ć","u","f","h","c","č","dž","š",
                "A","B","V","G","D","Đ","E","Ž","Z","I","J","K","L","Lj","M","N","Nj","O","P","R","S","T","Ć","U","F","H","C","Č","Dž","Š"]))
# The price list's names (some misspelt) -> OpenStreetMap's.
FIX = {
    "KRUŠEVAC east": "kruševac istok", "KRUŠEVAC west": "kruševac zapad",
    "NIČ Malča": "malča", "NIŠ Malča": "malča", "NiŠ istok": "niš istok", "BELA PALANK": "bela palanka",
    "VLAČICIN HAN": "vladičin han", "MEROČINA": "merošina", "MOROVIĆ / ADAŠEVCI": "adaševci",
    "ČAČAK (Pakovraće)": "pakovraće", "PRELJINA JUG": "preljina konjevići",
}
# One price-list name for several stations.
MANY = {"novi sad": ["novi sad - sever", "novi sad - jug"]}
# Canonical display names.
DISPLAY = {"BELA PALANK": "BELA PALANKA", "VLAČICIN HAN": "VLADIČIN HAN", "MEROČINA": "MEROŠINA", "NIČ Malča": "NIŠ Malča",
           "NiŠ istok": "NIŠ istok", "KRUŠEVAC east": "KRUŠEVAC istok", "KRUŠEVAC west": "KRUŠEVAC zapad", "PRESEVO": "PREŠEVO"}
SYSTEMS = {"BEOGRAD": "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad", "DIMITROVGRAD": "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad",
           "PRESEVO": "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad", "ŠID": "A3 Beograd – Šid",
           "STARA PAZOVA": "A1 Beograd – Subotica", "OBRENOVAC": "A2 Beograd – Požega"}


def lat(s):
    return "".join(CYR.get(c, c) for c in s)


def key(s):
    s = FIX.get(s.strip(), s.strip())
    s = re.sub(r"\s+", " ", lat(s)).strip().lower()
    for p in ("naplatna stanica ",):
        if s.startswith(p):
            s = s[len(p):]
    return s


def name(s):
    s = s.strip()
    return DISPLAY.get(s, s)


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def main(prices_txt, booths_path, out):
    origin = None
    prices = defaultdict(dict)
    for line in open(prices_txt, encoding="utf-8"):
        t = line.strip()
        if re.fullmatch(r"[A-ZČĆŠĐŽ ]{3,}", t) and t not in ("PUTARINA",):
            origin = t
            continue
        m = re.match(r"^\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s*$", line)
        if m and origin:
            sys_name = SYSTEMS[origin]
            prices[sys_name][name(origin) + "|" + name(m.group(6))] = {"K3": num(m.group(10)), "K4": num(m.group(11))}
    booths = defaultdict(list)
    for l in open(booths_path, encoding="utf-8"):
        f = json.loads(l.lstrip("\x1e"))
        p = f["properties"]
        if p.get("barrier") != "toll_booth":
            continue
        lon, la = f["geometry"]["coordinates"]
        for n in {p.get("name", ""), p.get("name:sr-Latn", "")}:
            if n:
                booths[key(n)].append({"name": "booth", "lat": round(la, 5), "lon": round(lon, 5)})
    systems, missing = [], []
    for sys_name, pr in prices.items():
        names = sorted({n for k in pr for n in k.split("|")})
        stations = []
        for n in names:
            raw = next((r for r, d in DISPLAY.items() if d == n), n)
            ks = MANY.get(key(raw), [key(raw)]) + [key(n)]
            pts = [p for k in ks for p in booths.get(k, [])]
            pts = [dict(t) for t in {tuple(sorted(p.items())) for p in pts}]
            if not pts:
                missing.append(n)
            stations.append({"name": n, "points": pts})
        systems.append({
            "name": sys_name,
            "law": "JP Putevi Srbije price list (posebna naknada za upotrebu autoputa, from 1 July 2026, with the Government's consent; Zakon o naknadama za korišćenje javnih dobara): EUR from the listed entry station; vehicle categories 3 (2-3 axles over 3.5 t) and 4 (4 or more axles)",
            "groups": [{"name": "K3", "min_kg": 3501, "max_axles": 3}, {"name": "K4", "min_kg": 3501, "min_axles": 4}],
            "stations": stations,
            "prices": pr,
        })
        print(sys_name, len(stations), "stations", len(pr), "prices")
    print("no OpenStreetMap booth:", missing)
    t = {
        "country": "RS", "currency": "EUR", "valid_from": "2026-07-01", "valid_to": "2026-12-31",
        "name": "Serbian motorway toll (putarina)",
        "law": "JP Putevi Srbije's price list in force from 1 July 2026 (EUR column, at NBS rate list 118 of 24 June 2024): toll from entry to exit station on the A1, A2, A3 and A4, by vehicle category. The list gives prices from Beograd, Dimitrovgrad, Preševo, Šid, Stara Pazova and Obrenovac to every station on their sections; other pairs aren't published there. The Belgrade bypass toll for category 4 (RSD per section, TAG only) isn't included.",
        "sources": [{"title": "JP Putevi Srbije: vehicle categories and toll price list", "url": "https://www.putevi-srbije.rs/index.php/sr/kategorizacija-vozila-cenovnik-putarine"},
                    {"title": "Price list (PDF)", "url": "https://www.putevi-srbije.rs/images/pdf/cene_putarina_lat.pdf"}],
        "vehicles": "Vehicles over 3.5 t (categories 3 and 4)", "min_kg": 3501,
        "tolled_roads": "Motorways A1 (Subotica–Beograd–Preševo), A2 (Obrenovac–Prilipac), A3 (Šid–Beograd) and A4 (Niš–Dimitrovgrad).",
        "closed_systems": systems,
    }
    json.dump(t, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
