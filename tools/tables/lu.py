"""Builds the Luxembourg Eurovignette table from the consolidated
Règlement grand-ducal du 21 mai 2019 on Legilux (fetch.py's
lu-rgd-2019.html).

Usage: python3 lu.py fetched/ out-dir -> out-dir/lu-<date>.json

Art. 1er, 2°, sets the charge, administrative costs included, for
vehicles over 12 t from 25 March 2025: per year, month, week and day
("Pour une journée"), by CO2 emission class, for class 1 by EURO class
(non-Euro, Euro I-V, "Euro VI ou moins polluants"), and by axles (three
at most, four at least). The table keeps the daily amounts. Point 3°
adds vehicles over 3.5 t and under 12 t from its own day (26 March 2027),
in the same way: a second table from that day has both. The annex lists
the roads charged.
"""
import datetime, html, json, os, re, sys

EURO = {"non-Euro": [0], "Euro I": [1], "Euro II": [2], "Euro III": [3], "Euro IV": [4], "Euro V": [5],
        "Euro VI ou moins polluants": [6]}


def cells(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<(td|th|p|div|tr|br|li|h\d)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("​", "").replace("\xa0", " ")
    return [re.sub(r"\s+", " ", c).strip() for c in t.split("\n") if c.strip()]


MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def since(cell):
    m = re.search(r"à compter du (\d+) (\w+) (\d{4})", cell, re.I)
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def day_rows(c, i, end, mass):
    """The daily rows of the point from c[i] to c[end], for mass (min_kg, max_kg)."""
    day = next(k for k in range(i, end) if c[k] == "Pour une journée")
    part = c[day + 1:end]
    assert part[:4] == ["Classe d’émissions de CO2", "Classe d’émissions Euro", "Trois essieux maximum", "Quatre essieux minimum"], part[:4]
    rows, co2, k = [], None, 4
    # An amount; the last cell may carry a footnote mark ("2 euros1 <").
    amount = lambda s: int(re.match(r"(\d+) euros", s).group(1))
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
    lo, hi = mass
    out = []
    for r in sorted(rows, key=lambda r: "euro" in r):
        sel = {k: v for k, v in r.items() if k in ("co2_class", "euro")}
        for axles, rate in (({"max_axles": 3}, r["max"]), ({"min_axles": 4}, r["min"])):
            out.append({"component": "toll", "min_kg": lo, **({"max_kg": hi} if hi else {}), **axles, **sel, "rate": rate})
    return out


def main(fetched, out):
    c = cells(os.path.join(fetched, "lu-rgd-2019.html"))
    i = next(k for k, x in enumerate(c) if x.startswith("À compter du") and c[k - 1] == "2°")
    assert "supérieure à 12 tonnes" in c[i], c[i]
    j = c.index("3°", i)
    assert c[j + 1].startswith("Nonobstant le point 2°") and "supérieure à 3,5 tonnes mais inférieure à 12 tonnes" in c[j + 1], c[j + 1]
    end = c.index("Art. 2.", j)
    over12, under12 = day_rows(c, i, j, (12001, None)), day_rows(c, j + 1, end, (3501, 11999))
    a = c.index("Liste des autoroutes et routes à caractère similaire soumises au droit d’usage :")
    roads = sorted(set(x for x in c[a:] if re.fullmatch(r"[AB]\d+( / [AB]\d+)?", x)), key=lambda x: int(re.sub(r"\D.*", "", x[1:])))
    first, second = since(c[i]), since(c[j + 1])
    if second <= first:
        sys.exit(f"3° from {second}, not after 2° from {first}")
    to = (datetime.date.fromisoformat(second) - datetime.timedelta(days=1)).isoformat()
    write(out, first, to, roads, over12, "2°", f"from {first}, for vehicles over 12 t", "Goods vehicles over 12 t maximum mass", 12001)
    write(out, second, None, roads, under12 + over12, "2° and 3°", f"for vehicles over 12 t (2°, from {first}) and over 3.5 t and under 12 t (3°, from {second})",
          "Goods vehicles over 3.5 t maximum mass (exactly 12 t is in neither point)", 3501)


def write(out, valid_from, valid_to, roads, rows, points, which, vehicles, min_kg):
    tb = {
        "country": "LU", "currency": "EUR", "valid_from": valid_from,
        "name": "Luxembourg road user charge (Eurovignette, droit d'usage)",
        # One Eurovignette day covers every state of the agreement (Guichet.lu).
        "shared_vignette": "eurovignette",
        "law": f"Loi modifiée du 24 février 1995 (Eurovignette Agreement of 9 February 1994); Règlement grand-ducal du 21 mai 2019, art. 1er, {points}, as amended by the RGD of 18 December 2024: {which}, a charge per day, week, month or year, administrative costs included, by CO2 emission class, EURO class (CO2 class 1) and axles (three at most, four at least). The table keeps the daily amount (one calendar day).",
        "sources": [{"title": "RGD du 21 mai 2019, consolidated (Legilux)", "url": "https://legilux.public.lu/eli/etat/leg/rgd/2019/05/21/a353/consolide/20241224"},
                    {"title": "Guichet.lu: Eurovignette, droit d'usage routier pour poids-lourds (a day's charge is a calendar day, 00:00 to 24:00)", "url": "https://guichet.public.lu/fr/entreprises/import-export/transit/transit-ue/e-vignette-poids-lourds.html"}],
        "vehicles": vehicles,
        "min_kg": min_kg,
        "tolled_roads": "The motorways and similar roads in the annex: " + ", ".join(roads) + ".",
        "per_day": True,
        "day": "calendar",
        "rows": rows,
    }
    if valid_to:
        tb["valid_to"] = valid_to
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"lu-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
