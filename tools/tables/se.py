"""Builds the Swedish road charge (vägavgift) table for foreign trucks
from each year's förordning (fetch.py's se-2025-918.pdf for 2026 and
se-2026-1806.pdf for 2027, converted with pdftotext -layout to .txt).

Usage: python3 se.py fetched/ out-dir -> out-dir/se-<year>-01-01.json

Lag (1997:1137) 11 § sets the charge in euro per year, month, week and
day by axles (at most 3, at least 4), CO2 emission class and, for CO2
class 1, EURO class; 23 § has it paid in kronor, at amounts the
government recalculates each year. The förordning gives those amounts in
kronor for the year it names ("avgiften till följande belopp för år
2026"). A foreign truck of 12 t or more pays per calendar day on
motorways and the roads in the law's annex 1 (5 §, 10 §). The table keeps
the daily amount: the last number on each row of the förordning's table.

From the day the law's 11 a § comes into force ("/Träder i kraft I:<day>/"
in se-1997-1137.html), vehicles over 3.5 t and under 12 t pay too, at
amounts in euro the government recalculates in kronor before that day
(transitional provision 5 of Lag (2024:293)). Until a förordning gives
them, the table from that day lists them as liable with no rate, so
their charge is reported missing, not as none.
"""
import datetime, html, json, os, re, sys

EURO = {"0": [0], "I": [1], "II": [2], "III": [3], "IV": [4], "V": [5], "VI": [6]}


# (source id, SFS number, URL): each year's amounts in kronor.
FORORDNINGAR = [
    ("se-2025-918", "2025:918", "https://svenskforfattningssamling.se/sites/default/files/sfs/2025-10/SFS2025-918.pdf"),
    ("se-2026-1806", "2026:1806", "https://svenskforfattningssamling.se/sites/default/files/sfs/2026-10/SFS2026-1806.pdf"),
]
def under_12t(fetched):
    """The day 11 a § (vehicles over 3.5 t and under 12 t) comes into force."""
    t = open(os.path.join(fetched, "se-1997-1137.html"), encoding="utf-8").read()
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    m = re.search(r"11 a § /Träder i kraft I:(\d{4}-\d\d-\d\d)/ För motorfordon och motorfordonskombination med en totalvikt som understiger 12 000 kilogram", t)
    if not m:
        sys.exit("se-1997-1137: no 11 a § to come into force (in force now? then give its day)")
    return m.group(1)


def main(fetched, out):
    since = under_12t(fetched)
    for sid, sfs, url in FORORDNINGAR:
        build(fetched, out, sid, sfs, url, since)


def build(fetched, out, sid, sfs, url, since):
    t = open(os.path.join(fetched, sid + ".txt"), encoding="utf-8").read()
    year = re.search(r"avgiften till följande belopp för år (\d{4})", t).group(1)
    if "11 a" in t:
        sys.exit(f"{sid}: amounts for 11 a § (under 12 t) to read")
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
    start, end = f"{year}-01-01", f"{year}-12-31"
    if start < since <= end:
        before = (datetime.date.fromisoformat(since) - datetime.timedelta(days=1)).isoformat()
        write(out, table(year, sfs, url, rows, start, before, None))
        start = since
    write(out, table(year, sfs, url, rows, start, end, since if since <= end else None))


def table(year, sfs, url, rows, start, end, since):
    """The table from start to end; since: the day 11 a § is in force, if by then."""
    under = since and since <= start
    tb = {
        "country": "SE", "currency": "SEK", "valid_from": start, "valid_to": end,
        "name": "Swedish road charge for heavy goods vehicles (vägavgift, Eurovignette)",
        # One Eurovignette day covers every state of the agreement (Guichet.lu).
        "shared_vignette": "eurovignette",
        "law": f"Lag (1997:1137) om vägavgift för vissa tunga fordon, 5, 10, 11 and 23 §§; amounts in kronor for {year} from Förordning ({sfs}), which the government sets for each calendar year (23 §): a time-based charge per calendar day, week, month or year for trucks and combinations of 12 t or more, by axles (at most 3, at least 4), CO2 emission class and, in CO2 class 1, EURO class. A foreign truck pays per day of use; a Swedish one pays yearly. The table keeps the daily amount. Not subject to VAT."
               + (f" From {since} the law also charges vehicles over 3.5 t and under 12 t (11 a §, Lag (2024:293)) at amounts in euro the government sets in kronor; Förordning ({sfs}) gives none, so they are liable here with no rate." if under else ""),
        "sources": [{"title": f"SFS {sfs} (Svensk författningssamling)", "url": url},
                    {"title": "Lag (1997:1137), consolidated (Riksdagen)", "url": "https://data.riksdagen.se/dokument/sfs-1997-1137.text"}],
        "vehicles": ("Trucks over 3.5 t and combinations with them" if under else "Trucks and articulated combinations of 12 t or more total weight") + ", for goods transport",
        "min_kg": 3501 if under else 12000,
        "tolled_roads": "Motorways and the roads in annex 1 of the law (for foreign vehicles; Swedish vehicles pay for all roads, yearly).",
        "per_day": True,
        "day": "calendar",
        "rows": rows,
    }
    if under:
        tb["not_priced"] = [f"vehicles over 3.5 t and under 12 t from {since} (11 a §): no amounts in kronor yet"]
    return tb


def write(out, tb):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"se-{tb['valid_from']}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(tb["rows"]), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
