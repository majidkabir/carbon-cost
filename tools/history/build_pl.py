"""Builds Poland's e-TOLL tables for each year from the Minister of
Infrastructure's obwieszczenie of that year's indexed rates (art. 13ha
ust. 8 of the ustawa o drogach publicznych), as pdftotext gives them.

Usage: python3 build_pl.py fetched/ out-dir

Each obwieszczenie has two annexes: 1 (national roads of class A and S:
motorways and expressways) and 2 (class GP and G), each with rows for
vehicles over 3.5 t and under 12 t, 12 t or more (permissible total mass
with the trailer), and buses, by EURO class (max. EURO 2, EURO 3, EURO 4,
min. EURO 5). The 2026 rates held until Dz.U. 2026 poz. 33 replaced them
on 1 February 2026.
"""
import json, os, re, sys

YEARS = [  # (file, valid_from, valid_to, M.P. reference, URL)
    ("pl-mp-2023-1459", "2024-01-01", "2024-12-31", "M.P. 2023 poz. 1459 (obwieszczenie of 20 December 2023)", "https://eli.gov.pl/eli/MP/2023/1459/ogl/pol/pdf"),
    ("pl-mp-2024-1037", "2025-01-01", "2025-12-31", "M.P. 2024 poz. 1037", "https://eli.gov.pl/api/acts/MP/2024/1037/text/O/M20241037.pdf"),
    ("pl-mp-2025-1244", "2026-01-01", "2026-01-31", "M.P. 2025 poz. 1244 (obwieszczenie of 3 December 2025)", "https://eli.gov.pl/api/acts/MP/2025/1244/text/O/M20251244.pdf"),
]
EURO = [[0, 1, 2], [3], [4], None]  # min. EURO 5: any other class


def main(fetched, out):
    for f, frm, to, ref, url in YEARS:
        txt = open(os.path.join(fetched, f + ".txt"), encoding="utf-8").read()
        lines = [[float(x.replace(",", ".")) for x in re.findall(r"\b\d,\d\d\b", l)] for l in txt.splitlines()]
        lines = [l for l in lines if len(l) == 4]
        assert len(lines) == 6, (f, lines)
        rows = []
        for road, (light, heavy) in (("motorway", lines[0:2]), ("other", lines[3:5])):
            for (lo, hi), vals in (((3501, 11999), light), ((12000, 0), heavy)):
                for e, v in zip(EURO, vals):
                    r = {"component": "toll", "road": road, "min_kg": lo}
                    if hi:
                        r["max_kg"] = hi
                    if e:
                        r["euro"] = e
                    rows.append(r | {"rate": v})
        tb = {
            "country": "PL", "currency": "PLN", "valid_from": frm, "valid_to": to,
            "name": "Polish electronic toll (e-TOLL)",
            "law": f"Ustawa o drogach publicznych, art. 13ha; the rates for {frm[:4]} announced in {ref}: annex 1 (class A and S roads) and annex 2 (class GP and G roads), by permissible total mass (with trailer: over 3.5 t and under 12 t; 12 t or more) and EURO class (max. EURO 2, EURO 3, EURO 4, min. EURO 5); no CO2 component.",
            "sources": [{"title": f"Monitor Polski: {ref}", "url": url}],
            "vehicles": "Motor vehicles and combinations over 3.5 t permissible total mass (with trailer), and buses",
            "min_kg": 3501,
            "tolled_roads": "e-TOLL sections of national roads: motorways and expressways (class A, S) and main roads (GP, G). Not included: the concession motorway sections (A1 Rusocin-Toruń, A2 Świecko-Konin, A4 Katowice-Kraków), charged by their operators.",
            "motorway_share": 1,
            "rows": rows,
        }
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"pl-{frm}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
