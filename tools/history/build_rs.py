"""Builds Serbia's toll (putarina) tables for past price lists from JP
Putevi Srbije's price list PDF (cene_putarina_lat.pdf) as the Internet
Archive kept it (tools/history/sources.json, rs-cene-<capture>), read as
tools/rs/build.py reads the current one: prices in EUR from Beograd,
Dimitrovgrad, Preševo, Šid, Stara Pazova and Obrenovac to each station,
categories 3 and 4. Each list's first day is its heading's "važi od";
it ends the day before the next list. The stations are placed as in the
current table (rates/data/rs-2026-07-01.json, from OpenStreetMap's toll
booths); a station the current table doesn't have isn't placed.

The lists of 1 April 2023 (in force until 9 July 2024), 10 January 2025
and 4 July 2025 weren't archived, so those periods have no table.

Usage: python3 build_rs.py fetched/ out-dir"""
import datetime, importlib.util, json, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
spec = importlib.util.spec_from_file_location("rs_build", os.path.join(ROOT, "tools", "rs", "build.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

PAGE = "https://www.putevi-srbije.rs/index.php/sr/kategorizacija-vozila-cenovnik-putarine"
# Each archived list: its source id, and the day the next list starts.
LISTS = [("rs-cene-20241214", "2025-01-10"), ("rs-cene-20260517", "2026-07-01")]
MONTHS = {"januara": 1, "februara": 2, "marta": 3, "aprila": 4, "maja": 5, "juna": 6, "jula": 7, "avgusta": 8,
          "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}


def prices(path):
    origin, out = None, defaultdict(dict)
    for line in open(path, encoding="utf-8"):
        t = line.strip()
        if re.fullmatch(r"[A-ZČĆŠĐŽ ]{3,}", t) and t not in ("PUTARINA",):
            origin = t
            continue
        m = re.match(r"^\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s*$", line)
        if m and origin:
            out[rs.SYSTEMS[origin]][rs.name(origin) + "|" + rs.name(m.group(6))] = {"K3": rs.num(m.group(10)), "K4": rs.num(m.group(11))}
    return out


def main(fetched, out):
    cur = json.load(open(os.path.join(ROOT, "rates", "data", "rs-2026-07-01.json"), encoding="utf-8"))
    pts = {(s["name"], st["name"]): st["points"] for s in cur["closed_systems"] for st in s["stations"]}
    srcs = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    os.makedirs(out, exist_ok=True)
    for sid, nxt in LISTS:
        text = open(os.path.join(fetched, sid + ".txt"), encoding="utf-8").read()
        m = re.search(r"važi od:?\s*(\d+)\.\s*([a-zčćšđž]+)\s+(\d{4})", text)
        if not m:
            sys.exit(f"{sid}: no 'važi od' date")
        start = datetime.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))).isoformat()
        rate = re.search(r"kursnoj listi NBS br\.\s*(\d+)\s*od\s*([\d.]+)", text)
        end = (datetime.date.fromisoformat(nxt) - datetime.timedelta(days=1)).isoformat()
        pr = prices(os.path.join(fetched, sid + ".txt"))
        systems, missing = [], []
        for name, p in pr.items():
            names = sorted({n for k in p for n in k.split("|")})
            stations = []
            for n in names:
                if (name, n) not in pts:
                    missing.append(n)
                stations.append({"name": n, "points": pts.get((name, n), [])})
            systems.append({"name": name,
                            "law": f"JP Putevi Srbije price list (posebna naknada za upotrebu autoputa, from {start}, with the Government's consent; Zakon o naknadama za korišćenje javnih dobara): EUR from the listed entry station; vehicle categories 3 (2-3 axles over 3.5 t) and 4 (4 or more axles)",
                            "groups": [{"name": "K3", "min_kg": 3501, "max_axles": 3}, {"name": "K4", "min_kg": 3501, "min_axles": 4}],
                            "stations": stations, "prices": p})
        if len(systems) != len(cur["closed_systems"]):
            sys.exit(f"{sid}: {len(systems)} systems")
        arch = srcs[sid]["url"]
        tb = {"country": "RS", "currency": "EUR", "valid_from": start, "valid_to": end, "name": cur["name"],
              "law": f"JP Putevi Srbije's price list in force from {start}" + (f" (EUR column, at NBS rate list {rate.group(1)} of {rate.group(2)})" if rate else "") + f", as the Internet Archive kept it ({sid[-8:]}): toll from entry to exit station on the A1, A2, A3 and A4, by vehicle category; in force until {end} (the next list). The list gives prices from Beograd, Dimitrovgrad, Preševo, Šid, Stara Pazova and Obrenovac to every station on their sections; other pairs aren't published there. Stations placed as in the current table" + (f"; not placed: {', '.join(sorted(set(missing)))}" if missing else "") + ".",
              "sources": [{"title": "JP Putevi Srbije: vehicle categories and toll price list", "url": PAGE},
                          {"title": f"Price list (PDF), Internet Archive copy of {sid[-8:]}", "url": arch}],
              "vehicles": cur["vehicles"], "min_kg": cur["min_kg"], "tolled_roads": cur["tolled_roads"], "closed_systems": systems}
        path = os.path.join(out, f"rs-{start}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, start, end, sum(len(s["prices"]) for s in systems), "prices; not placed:", sorted(set(missing)))


if __name__ == "__main__":
    main(*sys.argv[1:])
