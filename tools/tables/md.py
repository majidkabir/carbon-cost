"""Builds Moldova's vignette (vinieta) for trucks not registered in
Moldova: Codul fiscal, Titlul IX, Anexa nr. 2, item 4 (trucks and road
tractors by total mass), as e-Vinieta (S.A. Administrația Națională a
Drumurilor) publishes it; fetch.py's md-evinieta.html, or
browser/md-evinieta.txt read in Chrome. A per-day table at the 1-day
amount: over 3.5 t up to 10 t EUR 8, over 10 t up to 40 t EUR 11.

Usage: python3 md.py fetched/ out-dir -> out-dir/md-<date>.json
"""
import html, json, os, re, sys

BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")
START = "2026-11-13"  # the day the page was first read; it gives no date for the amounts


def text(fetched):
    p = os.path.join(fetched, "md-evinieta.html")
    if os.path.exists(p):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", re.sub(r"<(script|style).*?</\1>", " ", open(p, encoding="utf-8", errors="replace").read(), flags=re.S))))
        t = re.sub(r"(\s*\|\s*)+", " | ", t)
        if "de la 10 la 40 t inclusiv" in t:
            return t, "fetched"
    print("md-evinieta: the copy read in Chrome")
    return re.sub(r"\s+", " ", " ".join(l for l in open(os.path.join(BROWSER, "md-evinieta.txt"), encoding="utf-8") if not l.startswith("# "))), "browser"


def main(fetched, out):
    t, how = text(fetched)
    if not re.search(r"Anexa nr\. ?2", t):
        sys.exit("Moldova: no Anexa nr. 2")
    rows = {}
    for key, label in (("b", r"b\) de la 3,5 la 10 t inclusiv"), ("c", r"c\) de la 10 la 40 t inclusiv")):
        m = re.search(label + r" \| 1 \| (\d+) \| 7 \| (\d+) \| 30 \| (\d+) \| 90 \| (\d+) \| 12 luni \| (\d+)", t)
        if not m:
            sys.exit(f"Moldova: row {key} not read")
        rows[key] = [int(x) for x in m.groups()]
    tb = {
        "country": "MD", "currency": "EUR", "valid_from": START,
        "name": "Moldova vignette (vinieta), trucks not registered in Moldova",
        "law": (f"Codul fiscal, Titlul IX (taxele rutiere), Anexa nr. 2, item 4: the charge for using Moldova's roads by vehicles not registered in Moldova, "
                f"trucks and road tractors by total mass: over 3.5 t up to 10 t EUR {rows['b'][0]} a day ({rows['b'][1]} for 7 days, {rows['b'][4]} for 12 months), "
                f"over 10 t up to 40 t EUR {rows['c'][0]} a day ({rows['c'][1]} for 7 days, {rows['c'][4]} for 12 months). The table keeps the 1-day amount; "
                "trucks registered in Moldova pay instead a yearly road fee, not modelled. The page gives no date: valid_from is the day it was first read."),
        "sources": [{"title": "e-Vinieta (S.A. Administrația Națională a Drumurilor): Legislația" + (" (read in Chrome: tools/tables/browser/md-evinieta.txt)" if how == "browser" else ""), "url": "https://evinieta.gov.md/Home/Legislation"}],
        "vehicles": "Trucks and road tractors not registered in Moldova, over 3.5 t", "min_kg": 3501,
        "tolled_roads": "All public roads of the Republic of Moldova.",
        "per_day": True,
        "rows": [{"component": "toll", "min_kg": 3501, "max_kg": 10000, "rate": rows["b"][0]},
                 {"component": "toll", "min_kg": 10001, "rate": rows["c"][0]}],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"md-{START}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
