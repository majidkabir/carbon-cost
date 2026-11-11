"""Builds the Latvian road user charge table from the consolidated
Autoceļu lietošanas nodevas likums on likumi.lv (fetch.py's lv-aln.html).

Usage: python3 lv.py fetched/ out-dir -> out-dir/lv-<date>.json

Annex 2 ("Autoceļu lietošanas nodevas likmes") gives the charge in euro
for 1 day, 7 days, 30 days and a year, by maximum mass (3001-3500 kg,
3501-12000 kg, 12001 kg and over), for the heaviest also by axles (2 and
3, 4 and more), and by EURO class (0-II, III, IV, V and EEV, VI;
"Bezemisiju" zero-emission is CO2 class 5). The table keeps the 1-day
rate. The date the annex applies from is read from its heading ("stājas
spēkā 01.03.2026").
"""
import html, json, os, re, sys

EURO = [("EURO 0, I, II", [0, 1, 2]), ("EURO III", [3]), ("EURO IV", [4]), ("EURO V, EEV", [5]),
        ("EURO VI un mazāk piesārņojošs", [6]), ("Bezemisiju", None)]
MASS = {"1": {"min_kg": 3001, "max_kg": 3500}, "2": {"min_kg": 3501, "max_kg": 12000}, "3": {"min_kg": 12001}}
AXLES = {"2 un 3 asis": {"max_axles": 3}, "4 un vairāk asis": {"min_axles": 4}}


def text(path):
    t = re.sub(r"<[^>]+>", " ", open(path, encoding="utf-8").read())
    return re.sub(r"\s+", " ", html.unescape(t))


# The annex from 22 August 2017 to 28 February 2026: up to 3500 kg one
# rate; over it EURO 0-II, III, and IV and better ("IV un mazāk
# piesārņojošs"); over 12 t each EURO row by axles (up to 3, 4 or more).
EURO_2017 = [("EURO 0, I, II", [0, 1, 2]), ("EURO III", [3]), ("EURO IV un mazāk piesārņojošs", [4, 5, 6])]
EURO_2017_HEAVY = [("EURO 0 EURO I EURO II", [0, 1, 2]), ("EURO III", [3]), ("EURO IV un mazāk piesārņojošs", [4, 5, 6])]


def rows_2017(parts):
    rows = []
    for no, body in zip(parts[1::2], parts[2::2]):
        mass = MASS[no]
        if no == "1":
            m = re.search(r"gada likme (\d+) (\d+) (\d+) (\d+)", body)
            rows.append({"component": "toll", **mass, "rate": int(m.group(1))})
        elif no == "2":
            for label, euro in EURO_2017:
                m = re.search(re.escape(label) + r" (\d+) (\d+) (\d+) (\d+)", body)
                rows.append({"component": "toll", **mass, "euro": euro, "rate": int(m.group(1))})
        else:
            for label, euro in EURO_2017_HEAVY:
                m = re.search(re.escape(label) + r" ne vairāk kā 3 asis (\d+) \d+ \d+ \d+ ne mazāk kā 4 asis (\d+) \d+ \d+ \d+", body)
                rows.append({"component": "toll", **mass, "max_axles": 3, "euro": euro, "rate": int(m.group(1))})
                rows.append({"component": "toll", **mass, "min_axles": 4, "euro": euro, "rate": int(m.group(2))})
    return rows


# The annex from 1 January 2025 to 28 February 2026.
EURO_2025 = [("EURO 0, I, II", [0, 1, 2]), ("EURO III", [3]), ("EURO IV, V, EEV", [4, 5]),
             ("EURO VI un mazāk piesārņojošs", [6]), ("Bezemisiju", None)]


def rows_euro(parts, classes=EURO):
    """Rows of annex 2 by EURO class with a zero-emission ("Bezemisiju")
    row, as worded from 1 January 2025."""
    rows = []
    for no, body in zip(parts[1::2], parts[2::2]):
        mass = MASS[no]
        # One group per "EURO 0, I, II" row; over 12 t each names its axles.
        groups = []
        for g in body.split("EURO 0, I, II ")[1:]:
            ax = {}
            for lab, v in AXLES.items():
                if g.startswith(lab + " "):
                    g, ax = g[len(lab) + 1:], v
            groups.append(("EURO 0, I, II " + g, ax))
        if len(groups) != (2 if no == "3" else 1):
            sys.exit(f"annex 2 part {no}: {len(groups)} groups")
        for g, ax in groups:
            for label, euro in classes:
                m = re.search(re.escape(label) + r" (\d+) (\d+) (\d+) (\d+)", g)
                if m is None:
                    sys.exit(f"annex 2 part {no}: no {label} row")
                row = {"component": "toll", **mass, **ax}
                if euro is None:
                    row["co2_class"] = [5]
                else:
                    row["euro"] = euro
                row["rate"] = int(m.group(1))
                rows.append(row)
    # Zero-emission rows first: such a truck matches them whatever its EURO class.
    rows.sort(key=lambda r: "co2_class" not in r)
    return rows


def main(fetched, out):
    t = text(os.path.join(fetched, "lv-aln.html"))
    i = re.search(r"2\. pielikums (?:Autoceļu lietošanas nodevas likmes )?\(Pielikums", t).start()
    annex = t[i:t.index("Tiesību akta pase", i)]
    d = re.search(r"stājas spēkā (\d\d)\.(\d\d)\.(\d{4})", annex)
    valid_from = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
    parts = re.split(r" ([123])\. Transportlīdzekļiem ", annex)
    if "Bezemisiju" not in annex:
        return write(out, valid_from, rows_2017(parts), "Autoceļu lietošanas nodevas likums, Annex 2 as worded by the amendments of 28 July 2017 (in force 22 August 2017): a time-based charge in euro for 1 day, 7 days, 30 days or a year, by maximum mass (3001-3500 kg, 3501-12000 kg, 12001 kg and over), axles (up to 3, or 4 and more, over 12 t) and EURO class (0-II, III, IV and better). The table keeps the 1-day rate. A fee, without VAT.")
    write(out, valid_from, rows_euro(parts), "Autoceļu lietošanas nodevas likums, Annex 2 as worded by the amendments of 22 January 2026 (in force 1 March 2026): a time-based charge in euro for 1 day, 7 days, 30 days or a year, by maximum mass (3001-3500 kg, 3501-12000 kg, 12001 kg and over), axles (2 and 3, or 4 and more, over 12 t) and EURO class; zero-emission vehicles pay nothing. The table keeps the 1-day rate. A fee, without VAT.")


def write(out, valid_from, rows, law):
    tb = {
        "country": "LV", "currency": "EUR", "valid_from": valid_from,
        "name": "Latvian road user charge (autoceļu lietošanas nodeva)",
        "law": law,
        "sources": [{"title": "Autoceļu lietošanas nodevas likums, consolidated (likumi.lv)", "url": "https://likumi.lv/ta/id/185656-autocelu-lietosanas-nodevas-likums"}],
        "vehicles": "Goods vehicles and combinations from 3001 kg maximum mass",
        "min_kg": 3001,
        "tolled_roads": "The state main and regional road sections listed in Annex 1 of the law. Any use of them on a day needs that day's charge.",
        "per_day": True,
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"lv-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
