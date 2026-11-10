"""Builds Czechia's historical toll tables from the annexes of the
amending regulations to nařízení vlády č. 240/2014 Sb., as tabulated on
epravo.cz (the Sbírka's PDF of 40/2024 has its annexes as images).

Usage: python3 build_cz.py fetched/ out-dir

- 479/2020 Sb. (1 January 2021 to 29 February 2024): Annex 1 (motorways)
  and 2 (class I roads), each with a table for 5:00-22:00 and one for
  22:00-5:00; by mass (over 3.5 to under 7.5 t, 7.5 to under 12 t, 12 t or
  more), EURO group (0-IV; V and EEV; VI; VI on natural gas) and axles
  (2, 3, 4, 5 or more). The table keeps the 5:00-22:00 rates; the night
  rates are about 0.5% higher. Diesel EURO VI is used for EURO VI.
- 40/2024 Sb.: from 1 March 2024 the rates by EURO group and CO2 class
  (EURO 0-IV, V/EEV, VI in CO2 class 1; CO2 classes 2-5), first for 1-24
  March (čl. I bod 12), then from 25 March 2024 (bod 13).
- 299/2024 Sb.: the same structure from 1 January 2025.
"""
import html, json, os, re, sys

MASS = {"více než 3,5 tuny a méně než 7,5 tuny": (3501, 7499), "nejméně 7,5 tuny a méně než 12 tun": (7500, 11999), "nejméně 12 tun": (12000, 0)}
AXLES = [(2, 2), (3, 3), (4, 4), (5, 0)]
G16 = [{"euro": [0, 1, 2, 3, 4]}, {"euro": [5]}, {"euro": [6]}, None]  # the gas EURO VI column is left out
G28 = [{"co2_class": [1], "euro": [0, 1, 2, 3, 4]}, {"co2_class": [1], "euro": [5]}, {"co2_class": [1], "euro": [6]},
       {"co2_class": [2]}, {"co2_class": [3]}, {"co2_class": [4]}, {"co2_class": [5]}]


def tables(path):
    """The rate tables of an epravo page, in order: lists of (mass label,
    numbers) rows, and the text before each table."""
    t = open(path, encoding="utf-8", errors="replace").read()
    s = html.unescape(re.sub(r"<(td|th)[^>]*>", " | ", re.sub(r"</tr>", "\n", t)))
    s = re.sub(r"<[^>]+>", "", s).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip()]
    out, cur = [], None
    for x in lines:
        cells = [c.strip() for c in x.split("|")]
        if len(cells) > 2 and cells[1] in MASS:
            vals = [float(c.replace(",", ".")) for c in cells[2:] if c]
            if cur is None:
                cur = []
                out.append(cur)
            cur.append((cells[1], vals))
        elif cur is not None and len(cur) == 3:
            cur = None
    return out


def rows_of(table, road, groups):
    rows = []
    for label, vals in table:
        lo, hi = MASS[label]
        assert len(vals) == 4 * len(groups), (label, len(vals))
        for g, sel in enumerate(groups):
            if sel is None:
                continue
            for a, (amin, amax) in enumerate(AXLES):
                r = {"component": "toll", "road": road, "min_kg": lo}
                if hi:
                    r["max_kg"] = hi
                r["min_axles"] = amin
                if amax:
                    r["max_axles"] = amax
                rows.append(r | sel | {"rate": vals[g * 4 + a]})
    return rows


BASE = {
    "country": "CZ", "currency": "CZK", "name": "Czech electronic toll (Mýto CZ)",
    "vehicles": "Motor vehicles and combinations over 3.5 t maximum permissible mass (except buses, M2/M3, which have their own rates)",
    "min_kg": 3501, "tolled_roads": "Motorways (dálnice) and the tolled sections of class I roads (silnice I. třídy).", "motorway_share": 1,
}
SRC240 = {"title": "Nařízení vlády č. 240/2014 Sb., § 3 (rate structure)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2014/240"}


def save(out, name, tb):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, name)
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(tb["rows"]), "rows")


def main(fetched, out):
    # 479/2020: tables in order: Annex 1 day, Annex 1 night, Annex 2 day, Annex 2 night, then buses.
    t = tables(os.path.join(fetched, "cz-nv-479-2020.html"))
    assert all(len(x[0][1]) == 16 for x in t[:4]), [len(x[0][1]) for x in t]
    save(out, "cz-2021-01-01.json", {**BASE, "valid_from": "2021-01-01", "valid_to": "2024-02-29",
         "law": "Nařízení vlády č. 240/2014 Sb., § 3 and Annexes 1 (motorways) and 2 (class I roads), as worded by nařízení vlády č. 479/2020 Sb., in force 1 January 2021 to 29 February 2024: one rate per km by road category, maximum permissible mass, axles and EURO class (0-IV; V and EEV; VI). The table keeps the rates for 5:00-22:00; from 22:00 to 5:00 they are about 0.5% higher. Euro VI vehicles on natural gas or biomethane had lower rates, not in the table.",
         "sources": [{"title": "Nařízení vlády č. 479/2020 Sb. (epravo.cz)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2020/479"}, SRC240],
         "rows": rows_of(t[0], "motorway", G16) + rows_of(t[2], "other", G16)})
    # 40/2024: Annexes 1-2 for 1-24 March, then for 25 March on (Annexes 3-4 are buses).
    p40 = os.path.join(fetched, "cz-nv-40-2024.html")
    if os.path.exists(p40):
        t = [x for x in tables(p40) if len(x[0][1]) == 28]
        assert len(t) == 4, len(t)
        src = [{"title": "Nařízení vlády č. 40/2024 Sb. (epravo.cz)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2024/40"},
               {"title": "Nařízení vlády č. 40/2024 Sb., Sbírka zákonů PDF", "url": "https://epravo.cz/_dataPublic/sbirky/2024/Sb_2024_40_PZZ.pdf"}, SRC240]
        what = "one rate per km by road category, maximum permissible mass, axles, CO2 emission class and, in CO2 class 1, EURO class (0-IV; V and EEV; VI); the regulation gives no separate CO2 part"
        save(out, "cz-2024-03-01.json", {**BASE, "valid_from": "2024-03-01", "valid_to": "2024-03-24",
             "law": f"Nařízení vlády č. 240/2014 Sb., Annexes 1 and 2 as worded by čl. I bod 12 of nařízení vlády č. 40/2024 Sb., in force 1 to 24 March 2024: {what}.",
             "sources": src, "rows": rows_of(t[0], "motorway", G28) + rows_of(t[1], "other", G28)})
        save(out, "cz-2024-03-25.json", {**BASE, "valid_from": "2024-03-25", "valid_to": "2024-12-31",
             "law": f"Nařízení vlády č. 240/2014 Sb., Annexes 1 and 2 as worded by čl. I bod 13 of nařízení vlády č. 40/2024 Sb., in force 25 March to 31 December 2024: {what}.",
             "sources": src, "rows": rows_of(t[2], "motorway", G28) + rows_of(t[3], "other", G28)})
    t = [x for x in tables(os.path.join(fetched, "cz-nv-299-2024.html")) if len(x[0][1]) == 28]
    assert len(t) == 2, len(t)
    save(out, "cz-2025-01-01.json", {**BASE, "valid_from": "2025-01-01", "valid_to": "2025-12-31",
         "law": "Nařízení vlády č. 240/2014 Sb., § 3 and Annexes 1 (motorways) and 2 (class I roads), as worded by nařízení vlády č. 299/2024 Sb., in force 1 January 2025: one rate per km by road category, maximum permissible mass, axles, CO2 emission class and, in CO2 class 1, EURO class; the regulation gives no separate CO2 part.",
         "sources": [{"title": "Nařízení vlády č. 299/2024 Sb. (epravo.cz)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2024/299"}, SRC240],
         "rows": rows_of(t[0], "motorway", G28) + rows_of(t[1], "other", G28)})


if __name__ == "__main__":
    main(*sys.argv[1:])
