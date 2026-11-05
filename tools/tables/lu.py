"""Builds the Luxembourg Eurovignette table from the consolidated
Règlement grand-ducal du 21 mai 2019 on Legilux (fetch.py's
lu-rgd-2019.html).

Usage: python3 lu.py fetched/ out-dir -> out-dir/lu-<date>.json

Art. 1er, 2°, sets the charge, administrative costs included, for
vehicles over 12 t from 25 March 2025: per year, month, week and day
("Pour une journée"), by CO2 emission class, for class 1 by EURO class
(non-Euro, Euro I-V, "Euro VI ou moins polluants"), and by axles (three
at most, four at least). The table keeps the daily amounts. Point 3°
(3.5 to 12 t, from 26 March 2027) isn't in force yet. The annex lists the
roads charged.
"""
import html, json, os, re, sys

EURO = {"non-Euro": [0], "Euro I": [1], "Euro II": [2], "Euro III": [3], "Euro IV": [4], "Euro V": [5],
        "Euro VI ou moins polluants": [6]}


def cells(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<(td|th|p|div|tr|br|li|h\d)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("​", "").replace("\xa0", " ")
    return [re.sub(r"\s+", " ", c).strip() for c in t.split("\n") if c.strip()]


def main(fetched, out):
    c = cells(os.path.join(fetched, "lu-rgd-2019.html"))
    i = next(k for k, x in enumerate(c) if x.startswith("À compter du") and c[k - 1] == "2°")
    m = re.search(r"À compter du (\d+) (\w+) (\d{4})", c[i])
    months = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
              "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}
    valid_from = f"{m.group(3)}-{months[m.group(2)]:02d}-{int(m.group(1)):02d}"
    assert "supérieure à 12 tonnes" in c[i], c[i]
    end = next(k for k in range(i, len(c)) if c[k] == "3°")
    day = next(k for k in range(i, end) if c[k] == "Pour une journée")
    part = c[day + 1:end]
    assert part[:4] == ["Classe d’émissions de CO2", "Classe d’émissions Euro", "Trois essieux maximum", "Quatre essieux minimum"], part[:4]
    rows, co2, k = [], None, 4
    amount = lambda s: int(re.fullmatch(r"(\d+) euros", s).group(1))
    while k < len(part):
        if re.fullmatch(r"[1-5]", part[k]):
            co2 = int(part[k])
            k += 1
            if co2 > 1:
                rows.append({"co2_class": [co2], "max": amount(part[k]), "min": amount(part[k + 1])})
                k += 2
                continue
        if part[k] in EURO and co2 == 1:
            rows.append({"co2_class": [1], "euro": EURO[part[k]], "max": amount(part[k + 1]), "min": amount(part[k + 2])})
            k += 3
            continue
        sys.exit(f"unexpected cell {part[k]!r}")
    if len(rows) != 11:
        sys.exit(f"{len(rows)} daily rows, want 11")
    out_rows = []
    for r in sorted(rows, key=lambda r: "euro" in r):
        sel = {k: v for k, v in r.items() if k in ("co2_class", "euro")}
        out_rows.append({"component": "toll", "min_kg": 12001, "max_axles": 3, **sel, "rate": r["max"]})
        out_rows.append({"component": "toll", "min_kg": 12001, "min_axles": 4, **sel, "rate": r["min"]})
    a = c.index("Liste des autoroutes et routes à caractère similaire soumises au droit d’usage :")
    roads = sorted(set(x for x in c[a:] if re.fullmatch(r"[AB]\d+( / [AB]\d+)?", x)), key=lambda x: int(re.sub(r"\D.*", "", x[1:])))
    tb = {
        "country": "LU", "currency": "EUR", "valid_from": valid_from,
        "name": "Luxembourg road user charge (Eurovignette, droit d'usage)",
        "law": "Loi modifiée du 24 février 1995 (Eurovignette Agreement of 9 February 1994); Règlement grand-ducal du 21 mai 2019, art. 1er, 2°, as amended by the RGD of 18 December 2024: from 25 March 2025, for vehicles over 12 t, a charge per day, week, month or year, administrative costs included, by CO2 emission class, EURO class (CO2 class 1) and axles (three at most, four at least). The table keeps the daily amount (one calendar day).",
        "sources": [{"title": "RGD du 21 mai 2019, consolidated (Legilux)", "url": "https://legilux.public.lu/eli/etat/leg/rgd/2019/05/21/a353/consolide/20241224"}],
        "vehicles": "Goods vehicles over 12 t maximum mass",
        "min_kg": 12001,
        "tolled_roads": "The motorways and similar roads in the annex: " + ", ".join(roads) + ".",
        "per_day": True,
        "rows": out_rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"lu-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(out_rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
