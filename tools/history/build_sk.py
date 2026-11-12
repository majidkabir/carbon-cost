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
import html, json, os, re, sys

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


if __name__ == "__main__":
    main(*sys.argv[1:])
