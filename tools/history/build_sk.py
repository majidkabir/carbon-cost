"""Builds Slovakia's toll table for 1 July 2020 to 30 June 2025 from
nariadenie vlády SR č. 497/2013 Z. z. as in force then (Slov-Lex's
version of 1 July 2020; NV 418/2024 replaced it on 1 July 2025).

Usage: python3 build_sk.py fetched/ out-dir

Annex 1 gives the rate in EUR/km excluding VAT on motorways and
expressways, Annex 2 part 1 the same rates on class I roads parallel to
them, part 2 lower rates on other tolled class I roads; by vehicle
category (goods vehicles 3.5 to 12 t, any axles; 12 t or more with 2, 3,
4, 5 axles) and EURO group (0-II; III, IV; V, VI and EEV). Buses are left
out. As in the current table, km off motorways take the part 2 rate.
"""
import html, json, os, re, subprocess, sys

EURO = [[0, 1, 2], [3, 4], [5, 6]]
CATS = [("3 500 kg - 12 000 kg*", 3501, 11999, {}), ("12 000 kg a viac - 2 nápravy", 12000, 0, {"min_axles": 2, "max_axles": 2}),
        ("12 000 kg a viac - 3 nápravy", 12000, 0, {"min_axles": 3, "max_axles": 3}), ("12 000 kg a viac - 4 nápravy", 12000, 0, {"min_axles": 4, "max_axles": 4}),
        ("12 000 kg a viac - 5 náprav", 12000, 0, {"min_axles": 5})]


def tables(L):
    """The goods-vehicle rate tables in order: {category: [3 rates]}."""
    out, k = [], 0
    while True:
        try:
            k = L.index("| Nákladné vozidlá", k) + 1
        except ValueError:
            return out
        t = {}
        for label, *_ in CATS:
            j = L.index("| " + label, k) if "| " + label in L[k:k + 40] else None
            if j is None:
                break
            t[label] = [float(L[j + i].lstrip("| ").replace(" ", "").replace(",", ".")) for i in (1, 2, 3)]
        if len(t) == len(CATS):
            out.append(t)


def main(fetched, out):
    t = open(os.path.join(fetched, "sk-nv-497-2013.html"), encoding="utf-8").read()
    s = html.unescape(re.sub(r"<(td|th)[^>]*>", " | ", re.sub(r"</tr>", "\n", t))).replace("\xa0", " ")
    L = [re.sub(r"\s+", " ", x).strip() for x in re.sub(r"<[^>]+>", "", s).split("\n") if x.strip()]
    L = [x for x in L if x != "|"]
    assert "01.07.2020" in " ".join(L[:200]) and "30.06.2025" in " ".join(L[:200])
    tbs = tables(L)
    assert len(tbs) >= 3, len(tbs)
    mw, par, other = tbs[0], tbs[1], tbs[2]
    assert mw == par, "Annex 2 part 1 should repeat Annex 1"
    rows = []
    for road, tb in (("motorway", mw), ("other", other)):
        for label, lo, hi, ax in CATS:
            for e, v in zip(EURO, tb[label]):
                r = {"component": "toll", "road": road, "min_kg": lo}
                if hi:
                    r["max_kg"] = hi
                rows.append(r | ax | {"euro": e, "rate": v})
    tb = {
        "country": "SK", "currency": "EUR", "valid_from": "2020-07-01", "valid_to": "2025-06-30", "name": "Slovak electronic toll (mýto)",
        "law": "Nariadenie vlády SR č. 497/2013 Z. z. as in force 1 July 2020 to 30 June 2025: Annex 1 (motorways and expressways; Annex 2 part 1 repeats it for class I roads parallel to them) and Annex 2 part 2 (other tolled class I roads), EUR/km excluding VAT by vehicle category (3.5-12 t any axles; 12 t or more by 2, 3, 4, 5 axles) and EURO group (0-II; III, IV; V, VI, EEV).",
        "sources": [{"title": "NV 497/2013 Z. z., version from 1 July 2020 (Slov-Lex)", "url": "https://static.slov-lex.sk/static/SK/ZZ/2013/497/20200701.html"},
                    {"title": "NV 497/2013 Z. z., version from 1 July 2020, legally binding PDF", "url": "https://static.slov-lex.sk/static/pdf/SK/ZZ/2013/497/ZZ_2013_497_20200701.pdf"}],
        "vehicles": "Goods vehicles over 3.5 t (buses have their own rates)",
        "min_kg": 3501,
        "tolled_roads": "Tolled sections of motorways and expressways, and of class I roads; class I roads parallel to motorways pay the motorway rate, other class I roads the lower Annex 2 part 2 rate. Km off motorways are priced at the Annex 2 part 2 rate.",
        "motorway_share": 1,
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "sk-2020-07-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")
    nv418(fetched, out)


CATS418 = [({"min_kg": 3501, "max_kg": 12000}, "Nákladné vozidlá 3,5 – 12 ton"), ({"min_kg": 12001, "max_axles": 2}, "Nákladné vozidlá >12 ton – 2"),
           ({"min_kg": 12001, "min_axles": 3, "max_axles": 3}, "Nákladné vozidlá >12 ton – 3"),
           ({"min_kg": 12001, "min_axles": 4, "max_axles": 4}, "Nákladné vozidlá >12 ton – 4"), ({"min_kg": 12001, "min_axles": 5}, "Nákladné vozidlá >12 ton – 5")]
# The rate tables' ten columns: EURO 0, I, II, III, IV, V/EEV and VI in CO2 class 1, EURO VI in CO2 classes 2-3, 4, ZEV.
COLS418 = [{"euro": [e]} for e in range(7)] + [{"co2_class": [2, 3], "euro": [6]}, {"co2_class": [4], "euro": [6]}, {"co2_class": [5]}]
CO2_COL = [0, 1, 1, 2, 2, 3, 4, 5, 6, 7]  # Annex 3 part 2's eight columns: EURO 0, I-II, III-IV, V/EEV, VI, CO2 2-3, CO2 4, ZEV
AIR_ROW = [0, 1, 2, 3, 4, 5, 6, 6, 6, 7]  # Annex 3 part 3's rows: EURO 0 to VI, then "less than EURO VI and zero emission"


def nums(line):
    return [float(x.replace(",", ".")) for x in re.findall(r"\b\d,\d{4}\b", line)]


def goods(text, n):
    """The five goods-vehicle lines of a rate table, n rates each."""
    out = []
    for line in text.splitlines():
        for _, label in CATS418:
            if re.sub(r"\s+", " ", line).strip().startswith(label):
                v = nums(line)
                if len(v) == n:
                    out.append(v)
                break
    if len(out) != len(CATS418):
        sys.exit(f"{len(out)} goods-vehicle lines of {n} rates")
    return out


def pdf(fetched, sid):
    path = os.path.join(fetched, sid + ".pdf")
    subprocess.run(["pdftotext", "-layout", path, path[:-4] + ".txt"], check=True)
    return open(path[:-4] + ".txt", encoding="utf-8").read()


def nv418(fetched, out):
    """From 1 July 2025: nariadenie vlády č. 418/2024 Z. z. Annex 5
    (motorways) and Annex 6 part 2 (other class I roads) give the rates;
    Annex 3 their CO2 (part 2) and air-pollution (part 3) parts; the
    infrastructure part is the rest."""
    page = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", open(os.path.join(fetched, "sk-nv-418-2024.html"), encoding="utf-8").read())))
    if "418/2024" not in page or "01.07.2025" not in page:
        sys.exit("sk-nv-418-2024: not the version from 1 July 2025")
    p3, p5, p6 = (pdf(fetched, f"sk-nv-418-2024-{p}") for p in ("p3", "p5", "p6"))
    mw = goods(p5[:p5.index("Autobusy")], 10)
    part2 = p6[p6.index("2. SADZBY MÝTA"):p6.index("3. SADZBY MÝTA")]
    other = goods(part2[:part2.index("Autobusy")], 10)
    a2 = p3[p3.index("2. Poplatok za externé náklady spojené s emisiami CO2"):p3.index("3. Poplatok za externé náklady spojené so znečistením")]
    co2 = goods(a2[:a2.index("Autobusy")], 8)
    a3 = p3[p3.index("3. Poplatok za externé náklady spojené so znečistením"):]
    air = [nums(l) for l in a3.splitlines() if re.match(r"\s*(EURO|Menej ako EURO VI)", l) and len(nums(l)) == 2]
    if len(air) != 8:
        sys.exit(f"{len(air)} air-pollution rows")
    rows = []
    for road, rates in (("motorway", mw), ("other", other)):
        for (cat, _), total, c in zip(CATS418, rates, co2):
            heavy = cat["min_kg"] > 12000
            for col in reversed(range(10)):
                parts = {"co2": c[CO2_COL[col]], "air": air[AIR_ROW[col]][1 if heavy else 0]}
                parts = {"infrastructure": round(total[col] - parts["co2"] - parts["air"], 4), **parts}
                for comp, v in parts.items():
                    rows.append({"component": comp, "road": road, **cat, **COLS418[col], "rate": v})
    base = "https://static.slov-lex.sk/pdf/prilohy/SK/ZZ/2024/418/20250701_"
    tb = {
        "country": "SK", "currency": "EUR", "valid_from": "2025-07-01", "valid_to": "2026-12-31", "name": "Slovak electronic toll (mýto)",
        "law": "Nariadenie vlády SR č. 418/2024 Z. z., in force 1 July 2025: Annex 5 (motorways) and Annex 6 part 2 (class I roads not parallel to motorways) give the rate in EUR/km excluding VAT by vehicle category, EURO class and CO2 class; Annex 3 gives its CO2 and air-pollution parts (the infrastructure part is the rest).",
        "sources": [{"title": "NV 418/2024 Z. z. (Slov-Lex, version from 1 July 2025)", "url": "https://static.slov-lex.sk/static/SK/ZZ/2024/418/20250701.html"},
                    {"title": "Annex 3: infrastructure, CO2 and air-pollution charges", "url": base + "5704373-2.pdf"},
                    {"title": "Annex 5: rates on motorways", "url": base + "5704381-2.pdf"},
                    {"title": "Annex 6: rates on class I roads", "url": base + "5704385-2.pdf"}],
        "vehicles": "Goods vehicles over 3.5 t (buses have their own rates)", "min_kg": 3501,
        "tolled_roads": "Tolled sections of motorways and expressways, and of class I roads; class I roads parallel to motorways pay the motorway rate, other class I roads the lower Annex 6 part 2 rate, and the rest of the network a zero rate. Km off motorways are priced at the Annex 6 part 2 rate.",
        "motorway_share": 1,
        "rows": rows,
    }
    path = os.path.join(out, "sk-2025-07-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
