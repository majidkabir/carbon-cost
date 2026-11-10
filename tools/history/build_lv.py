"""Builds Latvia's road user charge from 1 January 2025, from the law of
4 December 2024 amending the Autoceļu lietošanas nodevas likums
(likumi.lv id 357477, fetched as lv-357477.html), which words annex 2
anew ("Izteikt 2. pielikumu šādā redakcijā") and comes into force on the
date it states ("Likums stājas spēkā 2025. gada 1. janvārī"). The table
ends the day before the next Latvian table in rates/data.

Usage: python3 build_lv.py fetched/ out-dir"""
import datetime, glob, json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tables"))
import lv  # noqa: E402

MONTHS = ["janvārī", "februārī", "martā", "aprīlī", "maijā", "jūnijā", "jūlijā", "augustā", "septembrī", "oktobrī", "novembrī", "decembrī"]


def main(fetched, out, data="rates/data"):
    t = lv.text(os.path.join(fetched, "lv-357477.html"))
    i = t.index("Izteikt 2. pielikumu šādā redakcijā")
    d = re.search(r"Likums stājas spēkā (\d{4})\. gada (\d+)\. (\w+)\.", t[i:])
    annex = t[i:i + d.start()]
    frm = f"{d.group(1)}-{MONTHS.index(d.group(3)) + 1:02d}-{int(d.group(2)):02d}"
    nxt = min(json.load(open(f))["valid_from"] for f in glob.glob(os.path.join(data, "lv-*.json")) if json.load(open(f))["valid_from"] > frm)
    to = (datetime.date.fromisoformat(nxt) - datetime.timedelta(days=1)).isoformat()
    rows = lv.rows_euro(re.split(r" ([123])\. Transportlīdzekļiem ", annex), lv.EURO_2025)
    lv.write(out, frm, rows, f"Autoceļu lietošanas nodevas likums, Annex 2 as worded by the law of 4 December 2024 (in force {frm}): a time-based charge in euro for 1 day, 7 days, 30 days, 9 months or a year, by maximum mass (3001-3500 kg, 3501-12000 kg, 12001 kg and over), axles (2 and 3, or 4 and more, over 12 t), EURO class and zero emission. The table keeps the 1-day rate. A fee, without VAT.")
    p = os.path.join(out, f"lv-{frm}.json")
    tb = json.load(open(p))
    tb["valid_to"] = to
    tb["sources"] = [{"title": "Grozījumi Autoceļu lietošanas nodevas likumā (4 December 2024)", "url": "https://likumi.lv/ta/id/357477"}]
    json.dump(tb, open(p, "w"), ensure_ascii=False, indent=1)
    print(p, len(rows), "rows, to", to)


if __name__ == "__main__":
    main(*sys.argv[1:])
