"""Builds Croatia's toll tables from 1 January 2024 to 31 December 2025
for Hrvatske autoceste's (HAC) motorways.

The prices are the current ones (rates/data/hr-2026-01-01.json, HAC's
price list): HAC hasn't changed its tolls for groups III and IV since
they were converted to euros on 1 January 2023 (Pravilnik o izmjenama i
dopunama Pravilnika o cestarini, NN 151/2022, art. 3: the converted
price of each section is its unit price). The builder checks that: each
archived copy of HAC's A1 price page (tools/history/sources.json,
hr-hac-a1-<date>, the prices from its default entry, Zagreb) must give
the current table's prices.

What changed are the ENC (electronic toll) discounts: until 30 June 2025
HAC gave heavy vehicles paying by prepaid ENC 21.74% off, and EURO V/EEV
vehicles 5% and EURO VI 12% more; from 1 July 2025 3% and 7% (HAC's
announcement of 27 June 2025; Pravilnik o izmjeni i dopuni Pravilnika o
cestarini, NN 110/2025, art. 10(5)). Before July 2025 HAC also gave
EURO IV an emission discount and post-paid ENC 30.43%; neither is
modelled (the tool takes the prepaid ENC discount).

Bina-Istra's Istrian Y (A8, A9) has no archived price list for 2024 and
2025, so it isn't in these tables.

Usage: python3 build_hr.py fetched/ out-dir"""
import copy, glob, html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VAT = 1.25
NN151 = "https://narodne-novine.nn.hr/clanci/sluzbeni/2022_12_151_2360.html"
NN110 = "https://narodne-novine.nn.hr/clanci/sluzbeni/2025_08_110_1580.html"
NEWS = "https://www.novilist.hr/novosti/hrvatska/hac-najavio-ujednacavanje-popusta-za-sve-enc-korisnike/"
PERIODS = [
    ("2024-01-01", "2025-06-30", [{"name": "ENC", "etc": True, "percent": 21.74},
                                  {"name": "ENC EURO V/EEV", "etc": True, "euro": [5], "percent": 5},
                                  {"name": "ENC EURO VI", "etc": True, "euro": [6], "percent": 12}],
     "ENC discounts until 30 June 2025: 21.74% (prepaid ENC), and 5% more for EURO V/EEV and 12% more for EURO VI (HAC's announcement of 27 June 2025 of the change from 1 July 2025); EURO IV's emission discount and the 30.43% post-paid discount of that time aren't modelled."),
    ("2025-07-01", "2025-12-31", None,
     "ENC discounts from 1 July 2025: 21.74%, and 3% more for EURO V/EEV and 7% more for EURO VI (HAC's announcement of 27 June 2025; Pravilnik o cestarini art. 10(5) as amended by NN 110/2025)."),
]


def rows(page):
    """(entry, {exit: (III, IV)}) from a HAC price page, EUR including VAT."""
    entry = re.search(r">\s*(?:Entry|Ulaz):\s*([^<]+)<", page)
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) >= 6 and "€" in cells[-1]:
            eur = [float(c.replace("€", "").strip().replace(".", "").replace(",", ".")) for c in cells[-2:]]
            out[cells[0]] = tuple(eur)
    return (html.unescape(entry.group(1)).strip() if entry else None), out


def main(fetched, out):
    cur = json.load(open(os.path.join(ROOT, "rates", "data", "hr-2026-01-01.json"), encoding="utf-8"))
    hac = [s for s in cur["closed_systems"] if "Bina-Istra" not in s["name"]]
    a1 = next(s for s in hac if s["name"].startswith("A1,"))
    srcs = {s["id"]: s["url"] for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    checked = []
    for p in sorted(glob.glob(os.path.join(fetched, "hr-hac-a1-*.html"))):
        sid = os.path.basename(p)[:-5]
        entry, got = rows(open(p, encoding="utf-8", errors="replace").read())
        if not got:
            sys.exit(f"{sid}: no prices")
        n = 0
        for ex, (c3, c4) in got.items():
            k = f"{entry}|{ex}"
            if k not in a1["prices"]:
                continue
            want = a1["prices"][k]
            if abs(want["III"] - round(c3 / VAT, 4)) > 0.006 or abs(want["IV"] - round(c4 / VAT, 4)) > 0.006:
                sys.exit(f"{sid}: {k} {c3}/{c4} incl. VAT, the current table {want}")
            n += 1
        if n < 10:
            sys.exit(f"{sid}: only {n} of its prices are in the current table")
        checked.append((sid, n))
        print(sid, n, "prices as today")
    if not checked:
        sys.exit("no archived HAC price page")
    os.makedirs(out, exist_ok=True)
    for start, end, disc, dnote in PERIODS:
        systems = copy.deepcopy(hac)
        for s in systems:
            if disc:
                s["discounts"] = copy.deepcopy(disc)
        tb = {"country": "HR", "currency": "EUR", "valid_from": start, "valid_to": end, "name": cur["name"],
              "law": "Zakon o cestama and Pravilnik o cestarini (NN 130/2013, 122/2014, 96/2017, 151/2022, 88/2024 and 110/2025): toll from entry to exit station on HAC's closed motorway systems, and per passage at the open stations Bregana and Rupa, by vehicle group (III: 2-3 axles over 3.5 t, IV: 4 or more axles). Prices are HAC's, unchanged for these groups since their conversion to euros on 1 January 2023 (NN 151/2022, art. 3), as the current table has them (checked against the Internet Archive's copies of HAC's A1 price page: " + ", ".join(f"{sid[-8:]} ({n} prices)" for sid, n in checked) + "), excluding 25% VAT. " + dnote + " Bina-Istra's Istrian Y (A8, A9) isn't included: its prices of that time weren't archived.",
              "sources": [{"title": "Hrvatske autoceste: toll rates (A1), Internet Archive copy of " + sid[-8:], "url": srcs[sid]} for sid, _ in checked]
              + [{"title": "Pravilnik o izmjenama i dopunama Pravilnika o cestarini (NN 151/2022)", "url": NN151},
                 {"title": "Pravilnik o izmjeni i dopuni Pravilnika o cestarini (NN 110/2025)", "url": NN110},
                 {"title": "Novi list: HAC's announcement of the ENC discounts from 1 July 2025", "url": NEWS}],
              "vehicles": cur["vehicles"], "min_kg": cur["min_kg"],
              "tolled_roads": "HAC's motorways (A1, A2, A3, A4, A5, A6, A7 Rupa, A10, A11); not Bina-Istra's Istrian Y (A8, A9).",
              "closed_systems": systems}
        path = os.path.join(out, f"hr-{start}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, start, end, len(systems), "systems")


if __name__ == "__main__":
    main(*sys.argv[1:])
