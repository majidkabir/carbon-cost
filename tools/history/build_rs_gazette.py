"""Builds Serbia's past toll (putarina) tables from the decision itself,
as each amendment printed its tables in the Official Gazette
(tools/rs/gazette.py): each from the day the amendment says it applies to
the day before the next one. The amendment in force is the tables
workflow's (tools/tables/rs.py).

The tables are scans; tools/rs/gazette_ocr.py has read each issue
(fetched/rs-sg-<n>-<year>.json). Where the Internet Archive kept Putevi
Srbije's price list of the same period, the table is held to that list's
RSD amounts; a difference is an error unless it is listed below, looked at
in the scan.

Usage: python3 build_rs_gazette.py fetched/ out-dir
"""
import datetime, importlib.util, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = {s["id"]: s["url"] for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
spec = importlib.util.spec_from_file_location("rs_gazette", os.path.join(HERE, "..", "rs", "gazette.py"))
gz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gz)

LIST_MONTHS = {"januara": 1, "februara": 2, "marta": 3, "aprila": 4, "maja": 5, "juna": 6, "jula": 7, "avgusta": 8,
               "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}
# Each amendment: its source, the issue, the day it applies from, the day
# the next one does, stations that start later (that day), and Putevi
# Srbije's archived price list of the period with the pairs where that list
# isn't the decision's amount.
ISSUES = [
    ("rs-sg-119-2023", "119/2023", "2024-01-01", "2024-07-10", {}, None, set()),
    # The list's 4.190 for Stara Pazova to Žednik, category IV: the scan
    # prints 4.150 in both cells.
    ("rs-sg-58-2024", "58/2024", "2024-07-10", "2025-01-10", {}, "rs-cene-20241214", {("STARA PAZOVA", "ŽEDNIK", "K4")}),
    ("rs-sg-107-2024", "107/2024", "2025-01-10", "2025-07-04", {}, None, set()),
    ("rs-sg-58-2025", "58/2025", "2025-07-04", "2026-01-01", {"Лучани": "2025-07-10", "Прилипац": "2025-07-10"}, None, set()),
    ("rs-sg-120-2025", "120/2025", "2026-01-01", "2026-07-01", {"Врба": "2026-01-14"}, "rs-cene-20260517", set()),
]


def list_from(text):
    m = re.search(r"važi od:?\s*(\d+)\.\s*([a-zčćšđž]+)\s+(\d{4})", text)
    return datetime.date(int(m.group(3)), LIST_MONTHS[m.group(2)], int(m.group(1))).isoformat() if m else None


def main(fetched, out):
    bs = gz.booths(os.path.join(fetched, "osm", "rs-osm.geojsonseq"))
    os.makedirs(out, exist_ok=True)
    for sid, issue, start, nxt, later, lst, known in ISSUES:
        path = os.path.join(fetched, sid + ".json")
        if not os.path.exists(path):
            print(f"{sid}: not read (no {sid}.json)")
            continue
        g = json.load(open(path, encoding="utf-8"))
        made = gz.tables(g, os.path.join(fetched, sid + ".pdf"), sid, issue, SOURCES[sid], start, nxt, later, bs)
        if lst:
            txt = os.path.join(fetched, lst + ".txt")
            if list_from(open(txt, encoding="utf-8").read()) != start:
                sys.exit(f"{lst}: not the price list from {start}")
            gz.check(made[-1][1], txt, f"{sid} and {lst}", known)
            for _, tb in made:
                tb["law"] += f" Held to Putevi Srbije's price list from {start} (its RSD amounts, the Internet Archive's copy): the same on every pair it has" + \
                    (f" but {', '.join(f'{a}–{b} category {g[1:]}' for a, b, g in sorted(known))}, where the scan is clear" if known else "") + "."
                tb["sources"].append({"title": f"JP Putevi Srbije's price list from {start}, Internet Archive copy", "url": SOURCES[lst]})
        for first, tb in made:
            json.dump(tb, open(os.path.join(out, f"rs-{first}.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
