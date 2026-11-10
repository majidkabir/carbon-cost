"""Builds Germany's toll table for 1 December 2023 to 30 June 2024 from
BFStrMG Anlage 11 (§ 14 Abs. 10), as inserted by Artikel 2 of the Drittes
Gesetz zur Änderung mautrechtlicher Vorschriften (BGBl. 2023 I Nr. 315),
from buzer.de's text of that article (gesetze-im-internet.de times out
for the workflow).

Usage: python3 build_de.py fetched/ out-dir -> out-dir/de-2023-12-01.json

The toll then applied from 7.5 t (§ 1 before 1 July 2024). Anlage 11
gives per km: 1. the infrastructure part by mass and axles; 2. the air
pollution part by category A-G (EURO class) and mass/axles; 3. the noise
part by mass/axles; 4. the CO2 part by CO2 emission class (class 1 also
by EURO class) and mass/axles (over 18 t: up to 3, 4, 5 or more axles).
Emission-free trucks were exempt until 31 December 2025 (§ 1 Abs. 2).
"""
import html, json, os, re, sys

# Mass/axle columns: (min_kg, max_kg, min_axles, max_axles)
COLS4 = [(7500, 11999, 0, 0), (12000, 18000, 0, 0), (18001, 0, 0, 3), (18001, 0, 4, 0)]
COLS5 = [(7500, 11999, 0, 0), (12000, 18000, 0, 0), (18001, 0, 0, 3), (18001, 0, 4, 4), (18001, 0, 5, 0)]
AIR = {"A": [6], "B": [5], "C": [4], "D": [3], "E": [2], "F": [0, 1]}
CO2_EURO = [[0, 1], [2, 3], [4, 5], [6]]


def num(s):
    return float(s.replace(",", "."))


def row(component, col, rate, **sel):
    lo, hi, amin, amax = col
    r = {"component": component, "min_kg": lo, "rate": rate}
    if hi:
        r["max_kg"] = hi
    if amin or amax:
        r["min_axles"], r["max_axles"] = amin, amax
    return r | sel


def main(fetched, out):
    t = open(os.path.join(fetched, "de-bfstrmg-anlage-11-buzer.html"), encoding="utf-8", errors="replace").read()
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t)).replace("\xa0", " ")
    L = [x.strip() for x in t.split("\n") if x.strip()]
    i = next(k for k, x in enumerate(L) if re.search(r"Mautsätze im Zeitraum vom 1\.\s*Dezember 2023 bis zum 30\.\s*Juni 2024", x))
    a = L[i:i + 400]
    nums = lambda seg: [num(x) for x in seg if re.fullmatch(r"\d+,\d+|0", x)]
    # 1. infrastructure: "... Achsen 0,067 Euro,"
    infra = [num(m) for m in re.findall(r"(\d+,\d+) Euro", " ".join(a[:a.index("2.")]))]
    assert len(infra) == 4, infra
    rows = [row("infrastructure", c, v) for c, v in zip(COLS4, infra)]
    # 2. air pollution, categories A-G.
    k = a.index("Kategorie", a.index("2."))
    for cat in "ABCDEFG":
        j = a.index(cat, k)
        vals = nums(a[j + 1:j + 5])
        assert len(vals) == 4, (cat, vals)
        for c, v in zip(COLS4, vals):
            rows.append(row("air", c, v, euro=AIR[cat], co2_class=[1, 2, 3, 4]) if cat != "G" else row("air", c, v, co2_class=[5]))
    # 3. noise.
    j = a.index("3.")
    seg = a[j:a.index("4.", j)]
    noise = nums(seg)[-4:]
    rows += [row("noise", c, v) for c, v in zip(COLS4, noise)]
    # 4. CO2: class 1 by EURO group, then classes 2-5.
    j = a.index("4.", j)
    seg = a[j:a.index("b)", j)]
    vals = nums(seg)
    assert len(vals) == 4 * 5 + 4 * 5, len(vals)
    for g in range(4):
        for c, v in zip(COLS5, vals[g * 5:g * 5 + 5]):
            rows.append(row("co2", c, v, euro=CO2_EURO[g], co2_class=[1]))
    for cls in range(2, 6):
        for c, v in zip(COLS5, vals[20 + (cls - 2) * 5:20 + (cls - 1) * 5]):
            rows.append(row("co2", c, v, co2_class=[cls]))
    tb = {
        "country": "DE", "currency": "EUR", "valid_from": "2023-12-01", "valid_to": "2024-06-30",
        "name": "German HGV toll (Lkw-Maut)",
        "law": "Bundesfernstraßenmautgesetz (BFStrMG) § 14 Abs. 10 and Anlage 11, as inserted by Artikel 2 of the Drittes Gesetz zur Änderung mautrechtlicher Vorschriften (BGBl. 2023 I Nr. 315): the toll rates from 1 December 2023 to 30 June 2024, for vehicles of 7.5 t or more (the toll covered lighter trucks only from 1 July 2024).",
        "sources": [{"title": "BFStrMG Anlage 11 (gesetze-im-internet.de)", "url": "https://www.gesetze-im-internet.de/bfstrmg/anlage_11.html"},
                    {"title": "Drittes Gesetz zur Änderung mautrechtlicher Vorschriften, Artikel 2 (buzer.de)", "url": "https://www.buzer.de/gesetz/16122/a304559.htm"}],
        "vehicles": "Vehicles and combinations of 7.5 t or more technically permissible maximum mass used for goods transport",
        "min_kg": 7500,
        "tolled_roads": "Federal motorways (Bundesautobahnen) and federal roads (Bundesstraßen).",
        "exemptions": [{"co2_class": [5], "until": "2025-12-31", "note": "Emission-free trucks (CO2 class 5) paid no toll until 31 December 2025 (BFStrMG § 1 Abs. 2)."}],
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "de-2023-12-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
