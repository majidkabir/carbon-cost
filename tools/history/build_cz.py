"""Builds Czechia's toll tables from the annexes of the amending
regulations to nařízení vlády č. 240/2014 Sb.: 479/2020 and 299/2024 as
tabulated on epravo.cz; 40/2024 from the Sbírka's PDF, whose annexes are
images, copied in transcribed/cz-40-2024.json (used only for the PDF with
the sha256 given there); 327/2025 from the Sbírka's PDF text.

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
- 327/2025 Sb.: the same structure from 1 January 2026.
"""
import html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

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
    t = annexes_40(fetched)
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
    t = pdf_327(fetched)
    save(out, "cz-2026-01-01.json", {"country": "CZ", "currency": "CZK", "valid_from": "2026-01-01", "valid_to": "2026-12-31", "name": BASE["name"],
         "law": "Nařízení vlády č. 240/2014 Sb., § 3 and Annexes 1 (motorways) and 2 (class I roads), as amended by nařízení vlády č. 327/2025 Sb., in force 1 January 2026. One rate per km by road category, maximum permissible mass, axles and EURO / CO2 emission class; the regulation gives no separate CO2 part.",
         "sources": [{"title": "Nařízení vlády č. 327/2025 Sb. (2026 toll rates, Annexes 1-2)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2025/327"}, SRC240],
         **{k: BASE[k] for k in ("vehicles", "min_kg", "tolled_roads", "motorway_share")},
         "rows": rows_of(t[0], "motorway", G28) + rows_of(t[1], "other", G28)})


def flat(s):
    return re.sub(r"\s+", " ", s)


def pdf_text(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout


def annexes_40(fetched):
    """40/2024's Annexes 1 and 2 under čl. I body 12 and 13, as transcribed
    from its PDF's images, for the PDF fetched."""
    tr = json.load(open(os.path.join(HERE, "transcribed", "cz-40-2024.json"), encoding="utf-8"))
    files = {f["url"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    f = files.get(tr["source"]["url"])
    if f is None or f["sha256"] != tr["source"]["sha256"]:
        sys.exit("cz-40-2024: the fetched PDF isn't the one transcribed")
    text = flat(pdf_text(os.path.join(fetched, f["file"])))
    for want in ("12. Přílohy č. 1 až 4 včetně nadpisů znějí:", "13. Přílohy č. 1 až 4 včetně nadpisů znějí:",
                 "Toto nařízení nabývá účinnosti dnem 1. března 2024, s výjimkou ustanovení čl. I bodu 13, které nabývá účinnosti dnem 25. března 2024."):
        assert want in text, want
    out = []
    for bod in (12, 13):
        for annex, road in ((1, "motorway"), (2, "other")):
            g = next(x for x in tr["tables"] if (x["bod"], x["annex"], x["road"]) == (bod, annex, road))
            assert list(g["rows"]) == list(MASS), list(g["rows"])
            out.append([(m, [float(v.replace(",", ".")) for v in g["rows"][m].split()]) for m in MASS])
    return out


def pdf_327(fetched):
    """327/2025's Annexes 1 and 2 (čl. I body 1 and 2) from the Sbírka PDF's
    text: three rows of 28 rates each; the consolidated text of 240/2014
    printed with it gives the same rates."""
    text = pdf_text(os.path.join(fetched, "cz-nv-327-2025-pdf.pdf"))
    assert "Toto nařízení nabývá účinnosti dnem 1. ledna 2026." in flat(text)

    def rates(part):
        rows = [[float(x.replace(",", ".")) for x in re.findall(r"\b\d,\d{4}\b", ln)] for ln in part.splitlines()]
        rows = [r for r in rows if r]
        assert all(len(r) == 28 for r in rows) and len(rows) == 3, [len(r) for r in rows]
        return list(zip(MASS, rows))

    a1, a2, a4 = (text.index(x) for x in ("1. Příloha č. 1 zní:", "2. Příloha č. 2 zní:", "3. Příloha č. 4 zní:"))
    amended = [rates(text[a1:a2]), rates(text[a2:a4])]
    full = text.index("Úplné znění aktu č. 240/2014 Sb.")
    c1 = text.index("Příloha č. 1", text.index("§7", full))
    c2, c3 = text.index("Příloha č. 2", c1), text.index("Příloha č. 3", c1)
    assert [rates(text[c1:c2]), rates(text[c2:c3])] == amended, "the consolidated text's Annexes 1-2 differ"
    return amended


if __name__ == "__main__":
    main(*sys.argv[1:])
