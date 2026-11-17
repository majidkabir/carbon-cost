#!/usr/bin/env python3
"""Dutch HGV charge (vrachtwagenheffing) from 1 July 2026, from the
Staatscourant texts that set its amounts:

- Stcrt. 2026, 3872: Regeling vrachtwagenheffing art. 5, the amounts of
  Wet vrachtwagenheffing art. 5 lid 1 at price level 2026, charged from
  1 July 2026;
- Stcrt. 2026, 18058: goedkeurend beleidsbesluit, 22.3% lower amounts from
  1 September to 31 December 2026;
- Stcrt. 2026, 33659: the amounts indexed for 1 January 2027.

Each sets three tables (infrastructure; air pollution and noise; CO2), each
by maximum mass of the combination: EURO 0 to EURO 6+ within CO2 class 1,
then CO2 classes 2 to 5. EURO 6+ is not a class of its own here; rows for
EURO 6 take the EURO 6 column.

Usage: python3 build_nl.py fetched/ out-dir -> out-dir/nl-2026-07-01.json, ...
"""
import json
import os
import re
import subprocess
import sys

BANDS = [("meer dan 3.500 tot 12.000", 3501, 11999), ("12.000 tot 18.000", 12000, 17999),
         (r"18.000 tot en met 32.0000?", 18000, 32000), ("meer dan 32.000", 32001, 0)]
COMPONENTS = ["infrastructure", "air_noise", "co2"]
ROADS = "Motorways and some provincial and municipal roads listed in the annex of the Wet vrachtwagenheffing."
VEHICLES = "Trucks of category N2 and N3 (over 3.5 t technical maximum mass), by maximum mass of the combination"
RIJK = {"title": "Rijksoverheid: vrachtwagenheffing from 1 July 2026", "url": "https://www.rijksoverheid.nl/onderwerpen/goederenvervoer/vrachtwagenheffing"}

PERIODS = [
    ("nl-stcrt-2026-3872", "2026-07-01", "2026-08-31",
     ["De vrachtwagenheffing wordt geheven met ingang van 1 juli 2026."],
     "Wet vrachtwagenheffing art. 5 lid 1, amounts indexed by Regeling IENW/BSK-2026/20152 (Staatscourant 2026, 3872)",
     [{"title": "Staatscourant 2026, nr. 3872: Regeling vrachtwagenheffing, indexed amounts (price level 2026)", "url": "https://zoek.officielebekendmakingen.nl/stcrt-2026-3872.pdf"}, RIJK]),
    ("nl-stcrt-2026-18058", "2026-09-01", "2026-12-31",
     ["keur ik goed dat van 1 september 2026 tot en met 31 december 2026",
      "De tijdelijke tarieven zoals opgenomen in artikel 1 van dit besluit, liggen 22,3% lager dan de tarieven in de wet."],
     "Goedkeurend beleidsbesluit tijdelijke verlaging tarieven Wet vrachtwagenheffing, IENW/BSK-2026/84850, art. 1 (Staatscourant 2026, 18058): 22.3% below the statutory rates",
     [{"title": "Staatscourant 2026, nr. 18058: temporary reduced rates, 1 September - 31 December 2026", "url": "https://zoek.officielebekendmakingen.nl/stcrt-2026-18058.html"}, RIJK]),
    ("nl-stcrt-2026-33659", "2027-01-01", "",
     ["Deze regeling treedt in werking met ingang van 1 januari 2027.",
      "De tabelcorrectiefactor over 2027 bedraagt 2,6 procent."],
     "Wet vrachtwagenheffing art. 5 lid 1, amounts indexed for 2027 by Regeling IENW/BSK-2026/181678 (Staatscourant 2026, 33659): the rates of 1 July 2026 times the 2027 tabelcorrectiefactor (2.6%); the temporary 22.3% reduction ended on 31 December 2026",
     [{"title": "Staatscourant 2026, nr. 33659: Regeling vrachtwagenheffing, amounts from 1 January 2027", "url": "https://zoek.officielebekendmakingen.nl/stcrt-2026-33659.html"}, RIJK]),
]


def rate(s):
    v = float(s.replace(",", "."))
    return 0 if v == 0 else v


def tables(text, n=6):
    """The n blocks (three components, each EURO columns then CO2 classes
    2-5), four mass bands each."""
    blocks, cur = [], []
    for line in text.splitlines():
        for i, (label, lo, hi) in enumerate(BANDS):
            m = re.match(r"\s*" + label + r"((?:\s+\d,\d{3})+)\s*$", line)
            if m:
                assert i == len(cur), (line, len(cur))
                cur.append((lo, hi, [rate(x) for x in m.group(1).split()]))
                if len(cur) == 4:
                    blocks.append(cur)
                    cur = []
    assert not cur and len(blocks) == n, (len(blocks), cur)
    for k, b in enumerate(blocks):
        assert all(len(v) == (8 if k % 2 == 0 else 4) for _, _, v in b), b
    return blocks


def rows_of(blocks):
    rows = []
    for c, comp in enumerate(COMPONENTS):
        euro, cls = blocks[2 * c], blocks[2 * c + 1]
        for (lo, hi, ev), (lo2, _, cv) in zip(euro, cls):
            assert lo == lo2
            for e in range(7):  # EURO 0..6; the EURO 6+ column is left out
                r = {"component": comp, "min_kg": lo, "euro": [e], "co2_class": [1], "rate": ev[e]}
                rows.append(r | ({"max_kg": hi} if hi else {}))
            for k, v in zip(range(2, 6), cv):
                r = {"component": comp, "min_kg": lo, "co2_class": [k], "rate": v}
                rows.append(r | ({"max_kg": hi} if hi else {}))
    return rows


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    for src, frm, to, phrases, law, sources in PERIODS:
        text = subprocess.run(["pdftotext", "-layout", os.path.join(fetched, src + ".pdf"), "-"], capture_output=True, text=True, check=True).stdout
        flat = re.sub(r"\s+", " ", text.replace("-\n", "-"))
        for p in phrases:
            assert p in flat, (src, p)
        decree, _, notes = text.partition("TOELICHTING")
        blocks = tables(decree)
        if src == "nl-stcrt-2026-18058":
            # The explanatory notes repeat the sum of the three components.
            for k, total in enumerate(tables(notes, 2)):
                for b in range(4):
                    got = [round(sum(blocks[2 * c + k][b][2][i] for c in range(3)), 3) for i in range(len(total[b][2]))]
                    assert got == total[b][2], (k, b, got, total[b][2])
        rows = rows_of(blocks)
        tb = {"country": "NL", "currency": "EUR", "valid_from": frm}
        if to:
            tb["valid_to"] = to
        tb |= {"name": "Dutch HGV charge (vrachtwagenheffing)", "law": law, "sources": sources,
               "vehicles": VEHICLES, "min_kg": 3501, "tolled_roads": ROADS, "rows": rows}
        path = os.path.join(out, f"nl-{frm}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
