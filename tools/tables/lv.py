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


def main(fetched, out):
    t = text(os.path.join(fetched, "lv-aln.html"))
    i = t.index("2. pielikums (Pielikums")
    annex = t[i:t.index("Tiesību akta pase", i)]
    d = re.search(r"stājas spēkā (\d\d)\.(\d\d)\.(\d{4})", annex)
    valid_from = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
    parts = re.split(r" ([123])\. Transportlīdzekļiem ", annex)
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
            for label, euro in EURO:
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
    tb = {
        "country": "LV", "currency": "EUR", "valid_from": valid_from,
        "name": "Latvian road user charge (autoceļu lietošanas nodeva)",
        "law": "Autoceļu lietošanas nodevas likums, Annex 2 as worded by the amendments of 22 January 2026 (in force 1 March 2026): a time-based charge in euro for 1 day, 7 days, 30 days or a year, by maximum mass (3001-3500 kg, 3501-12000 kg, 12001 kg and over), axles (2 and 3, or 4 and more, over 12 t) and EURO class; zero-emission vehicles pay nothing. The table keeps the 1-day rate. A fee, without VAT.",
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
