"""Builds the Swedish road charge (vägavgift) table for foreign trucks
from Förordning (2025:918) (fetch.py's se-2025-918.pdf, converted with
pdftotext -layout to se-2025-918.txt).

Usage: python3 se.py fetched/ out-dir -> out-dir/se-<year>-01-01.json

Lag (1997:1137) 11 § sets the charge in euro per year, month, week and
day by axles (at most 3, at least 4), CO2 emission class and, for CO2
class 1, EURO class; 23 § has it paid in kronor, at amounts the
government recalculates each year. The förordning gives those amounts in
kronor for the year it names ("avgiften till följande belopp för år
2026"). A foreign truck of 12 t or more pays per calendar day on
motorways and the roads in the law's annex 1 (5 §, 10 §). The table keeps
the daily amount: the last number on each row of the förordning's table.
"""
import json, os, re, sys

EURO = {"0": [0], "I": [1], "II": [2], "III": [3], "IV": [4], "V": [5], "VI": [6]}


def main(fetched, out):
    t = open(os.path.join(fetched, "se-2025-918.txt"), encoding="utf-8").read()
    year = re.search(r"avgiften till följande belopp för år (\d{4})", t).group(1)
    rows = []
    i3, i4 = t.index("Högst 3 axlar"), t.index("Minst 4 axlar")
    for block, head, axles in ((t[i3:i4], "Högst 3 axlar", {"max_axles": 3}), (t[i4:], "Minst 4 axlar", {"min_axles": 4})):
        co2_rows, euro_rows = [], []
        for line in block.splitlines():
            tok = line.split()
            if not tok or not re.fullmatch(r"\d+", tok[-1]):
                continue
            day = int(tok[-1])
            if tok[0] == "1" and len(tok) > 1 and tok[1] == "0":
                euro_rows.append(([0], day))
            elif tok[0] in EURO and tok[0] != "0":
                euro_rows.append((EURO[tok[0]], day))
            elif tok[0] in ("2", "3", "4", "5") and len(tok) > 2:
                co2_rows.append((int(tok[0]), day))
        if len(euro_rows) != 7 or len(co2_rows) != 4:
            sys.exit(f"{head}: {len(euro_rows)} EURO rows, {len(co2_rows)} CO2 rows")
        for c, day in co2_rows:
            rows.append({"component": "toll", "min_kg": 12000, **axles, "co2_class": [c], "rate": day})
        for e, day in euro_rows:
            rows.append({"component": "toll", "min_kg": 12000, **axles, "co2_class": [1], "euro": e, "rate": day})
    # CO2 classes 2-5 first: they are priced whatever the EURO class.
    rows.sort(key=lambda r: "euro" in r)
    tb = {
        "country": "SE", "currency": "SEK", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "name": "Swedish road charge for heavy goods vehicles (vägavgift, Eurovignette)",
        "law": f"Lag (1997:1137) om vägavgift för vissa tunga fordon, 5, 10, 11 and 23 §§; amounts in kronor for {year} from Förordning (2025:918): a time-based charge per calendar day, week, month or year for trucks and combinations of 12 t or more, by axles (at most 3, at least 4), CO2 emission class and, in CO2 class 1, EURO class. A foreign truck pays per day of use; a Swedish one pays yearly. The table keeps the daily amount. Not subject to VAT.",
        "sources": [{"title": "SFS 2025:918 (Svensk författningssamling)", "url": "https://svenskforfattningssamling.se/sites/default/files/sfs/2025-10/SFS2025-918.pdf"},
                    {"title": "Lag (1997:1137), consolidated (Riksdagen)", "url": "https://data.riksdagen.se/dokument/sfs-1997-1137.text"}],
        "vehicles": "Trucks and articulated combinations of 12 t or more total weight, for goods transport",
        "min_kg": 12000,
        "tolled_roads": "Motorways and the roads in annex 1 of the law (for foreign vehicles; Swedish vehicles pay for all roads, yearly).",
        "per_day": True,
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"se-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
