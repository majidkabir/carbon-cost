"""Builds Bulgaria's toll (BG TOLL) tables before June 2026 from the
Държавен вестник texts the history workflow fetched (tools/history/
sources.json, bg-dv-*): the toll table of чл. 25, ал. 1 of the Тарифа за
таксите, които се събират за преминаване и ползване на републиканската
пътна мрежа (ПМС № 370/2019) in each version, per km by vehicle
category, EURO class and road class (АМ motorway, I клас, II клас).

The dates come from the decrees and from the consolidated text in the
Административен регистър (bg-iisda-tarifa, an RTF), whose note on чл. 25,
ал. 1 lists each amendment with the day it took effect.

Rows: goods vehicles only (buses have their own rates, as in the current
table). Km off motorways are priced at the I клас rate (II клас is lower;
the route's road classes don't tell I from II here). EEV is priced as
EURO V (the tool has no EEV class; Bulgaria prices it as EURO VI).

Usage: python3 build_bg.py fetched/ out-dir"""
import html, json, os, re, sys

from bs4 import BeautifulSoup

DV = "https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat="
IISDA = "https://iisda.government.bg/adm_services/service_regulatory_file/22321_97892"

CATS = [  # the table's vehicle rows, as the current table's weight and axle bounds
    ("до 12 т", {"min_kg": 3501, "max_kg": 12000}),
    ("2 – 3 оси", {"min_kg": 12001, "max_axles": 3}),
    ("4 и повече оси", {"min_kg": 12001, "min_axles": 4}),
]
EURO = [("VI", [6]), ("V", [5]), ("III", [3, 4]), ("0", [0, 1, 2])]

# Each version: the fetched text, which toll table in it (the n-th with
# "Цена на тол такса"), its currency, dates, and what the law says.
PERIODS = [
    {"src": "bg-dv-142-2022", "nth": 1, "currency": "BGN", "valid_from": "2024-01-01", "valid_to": "2025-03-31",
     "law": "Тарифа за таксите, които се събират за преминаване и ползване на републиканската пътна мрежа (ПМС № 370/2019), чл. 25, ал. 1, т. 2 as amended by Постановление № 142 от 24 юни 2022 г. (ДВ бр. 49 от 30.06.2022), in force from 1 July 2023 (Постановление № 495 от 29 декември 2022 г., ДВ бр. 104 от 30.12.2022, moved it from 1 January 2023) until 31 March 2025 (Постановление № 20 от 31 март 2025 г., ДВ бр. 28 от 01.04.2025, replaced it from 1 April 2025): BGN/km by vehicle category, EURO class and road class. No VAT is charged.",
     "sources": [("Държавен вестник бр. 49/2022: Постановление № 142 (toll rates of чл. 25, ал. 1, т. 2)", DV + "174365"),
                 ("Държавен вестник бр. 104/2022: Постановление № 495 (т. 2 from 1 July 2023)", DV + "182660"),
                 ("Държавен вестник бр. 28/2025: Постановление № 20 (new rates from 1 April 2025)", DV + "233823")]},
    {"src": "bg-dv-20-2025", "nth": 0, "currency": "BGN", "valid_from": "2025-04-01", "valid_to": "2025-08-31",
     "law": "Тарифа за таксите, които се събират за преминаване и ползване на републиканската пътна мрежа (ПМС № 370/2019), чл. 25, ал. 1, т. 1 as amended by Постановление № 20 от 31 март 2025 г. (ДВ бр. 28 от 01.04.2025), in force 1 April to 31 August 2025 (§ 5: т. 2 from 1 September 2025): BGN/km by vehicle category, EURO class and road class. No VAT is charged.",
     "sources": [("Държавен вестник бр. 28/2025: Постановление № 20 (toll rates of чл. 25, ал. 1, т. 1 and т. 2)", DV + "233823")]},
    {"src": "bg-dv-20-2025", "nth": 1, "currency": "BGN", "valid_from": "2025-09-01", "valid_to": "2025-12-31",
     "law": "Тарифа за таксите, които се събират за преминаване и ползване на републиканската пътна мрежа (ПМС № 370/2019), чл. 25, ал. 1, т. 2 as amended by Постановление № 20 от 31 март 2025 г. (ДВ бр. 28 от 01.04.2025), in force from 1 September 2025 (§ 5) until 31 December 2025 (Постановление № 208 от 9 октомври 2025 г., ДВ бр. 85 от 14.10.2025, replaced it in euros from 1 January 2026): BGN/km by vehicle category, EURO class and road class. No VAT is charged.",
     "sources": [("Държавен вестник бр. 28/2025: Постановление № 20 (toll rates of чл. 25, ал. 1, т. 1 and т. 2)", DV + "233823"),
                 ("Държавен вестник бр. 85/2025: Постановление № 208 (rates in euros from 1 January 2026)", DV + "238097")]},
    {"src": "bg-dv-208-2025", "nth": 0, "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-05-31",
     "law": "Тарифа за таксите, които се събират за преминаване и ползване на републиканската пътна мрежа (ПМС № 370/2019), чл. 25, ал. 1 as amended by Постановление № 208 от 9 октомври 2025 г. (ДВ бр. 85 от 14.10.2025), in force from 1 January 2026 (the day Bulgaria adopted the euro, § 15) until 31 May 2026 (Постановление № 64 от 26 май 2026 г., ДВ бр. 49 от 29.05.2026, from 1 June 2026): EUR/km by vehicle category, EURO class and road class. No VAT is charged.",
     "sources": [("Държавен вестник бр. 85/2025: Постановление № 208 (toll rates of чл. 25, ал. 1 in euros)", DV + "238097"),
                 ("Държавен вестник бр. 49/2026: Постановление № 64 (rates from 1 June 2026)", DV + "243642")]},
]


def num(s):
    return float(s.replace(",", ".").strip())


def toll_tables(path):
    soup = BeautifulSoup(open(path, "rb").read().decode("utf-8", "replace"), "lxml")
    out = []
    for t in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])] for r in t.find_all("tr")]
        if any("Цена на тол такса" in " ".join(r) for r in rows):
            out.append(rows)
    return out


def rates(rows):
    """{(category index, euro index): (motorway, class I, class II)} for goods vehicles."""
    out, cat = {}, None
    for r in rows:
        cells = [c for c in r if c]
        if not cells:
            continue
        head = " ".join(cells)
        if "превоз на пътници" in head:
            cat = None
            continue
        for i, (key, _) in enumerate(CATS):
            if "Товарен автомобил" in head and key in head:
                cat = i
        nums = [c for c in cells if re.fullmatch(r"\d+,\d+", c)]
        if cat is None or len(nums) != 3:
            continue
        label = next(c for c in cells if re.search(r"(ЕВРО|EBPO|EURO)", c))
        e = next(j for j, (k, _) in enumerate(EURO) if re.search(r"\b" + k + r"\b", label.replace(",", " ")))
        out[(cat, e)] = tuple(num(n) for n in nums)
    if len(out) != len(CATS) * len(EURO):
        sys.exit(f"toll table: {len(out)} goods-vehicle rows, want {len(CATS) * len(EURO)}")
    return out


def check_dates(fetched):
    """The consolidated text's note on чл. 25, ал. 1 must list the
    amendments the periods assume."""
    p = os.path.join(fetched, "bg-iisda-tarifa.html")
    raw = open(p, "rb").read().decode("latin-1")
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1251"), raw)
    text = re.sub(r"\s+", " ", re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", raw))
    i = text.find("Чл. 25")
    note = text[i:i + 400]
    for want in ("бр. 104 от 2022 г., в сила от 1.01.2023 г.", "бр. 28 от 2025 г., в сила от 1.04.2025 г.",
                 "бр. 85 от 2025 г., в сила от 1.01.2026 г.", "бр. 49 от 2026 г."):
        if want.replace(" ", "") not in note.replace(" ", ""):
            sys.exit(f"consolidated чл. 25: no {want!r} in {note!r}")


def main(fetched, out):
    check_dates(fetched)
    os.makedirs(out, exist_ok=True)
    for p in PERIODS:
        tabs = toll_tables(os.path.join(fetched, p["src"] + ".html"))
        r = rates(tabs[p["nth"]])
        rows = []
        for road, col in (("motorway", 0), ("other", 1)):
            for ci, (_, bounds) in enumerate(CATS):
                for ei, (_, euro) in enumerate(EURO):
                    rows.append({"component": "infrastructure", "road": road, **bounds, "euro": euro, "rate": r[(ci, ei)][col]})
        tb = {"country": "BG", "currency": p["currency"], "valid_from": p["valid_from"], "valid_to": p["valid_to"],
              "name": "Bulgarian distance toll (BG TOLL)", "law": p["law"],
              "sources": [{"title": t, "url": u} for t, u in p["sources"]],
              "vehicles": "Goods vehicles over 3.5 t technically permissible maximum mass (buses have their own rates)",
              "min_kg": 3501,
              "tolled_roads": "Motorways and class I roads (about 3,115 km), and tolled class II roads. Km off motorways are priced at the class I rate; class II rates are lower.",
              "motorway_share": 1, "rows": rows}
        path = os.path.join(out, f"bg-{p['valid_from']}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
