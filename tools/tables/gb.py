"""Builds the UK HGV levy table for non-UK trucks from GOV.UK's guidance
"How to use the HGV levy service" (fetch.py's gb-levy-guide.html).

Usage: python3 gb.py fetched/ out-dir -> out-dir/gb-<date>.json

The HGV Road User Levy Act 2013 (section 6, Schedule 1 Tables 1, 1A and
1B) charges a non-UK HGV of 12 t or more a daily rate for each day it
uses a main road (A or M roads), by band of maximum permitted (revenue)
weight and by whether it meets Euro 6. The guidance tabulates the rates
in force ("Levy rates from 1 April 2026"): one table for Euro 6, one for
Euro 5 or older, each with bands A (12,000 to 31,000 kg), B (31,001 to
38,000) and C (38,001 and over). Zero-emission HGVs are exempt. (The
legislation.gov.uk pages can't be kept on the tables-out branch: GitHub's
secret scanning rejects them.)
"""
import html, json, os, re, sys

MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}


def main(fetched, out, name="gb-levy-guide.html", extra_sources=(), valid_to=None, valid_from=None):
    t = open(os.path.join(fetched, name), encoding="utf-8").read()
    t = t[t.index('<h2 id="hgv-levy-rates"'):]
    t = t[:t.index('<h2 id="hgv-levy-account"')]
    c = re.sub(r"<(td|th|tr|p|h\d|li)[^>]*>", "\n", t)
    c = [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "", c)).split("\n") if x.strip()]
    if valid_from is None:
        d = re.search(r"Levy rates from (\d+) (\w+) (\d{4})", " ".join(c))
        valid_from = f"{d.group(3)}-{MONTHS[d.group(2)]:02d}-{int(d.group(1)):02d}"
    rows = [{"component": "toll", "min_kg": 12000, "co2_class": [5], "rate": 0}]
    for head, euro in (("Euro 6 vehicles", [6]), ("Euro 5 or older vehicles", [0, 1, 2, 3, 4, 5])):
        k = c.index(head)
        k = c.index("Yearly rate", k) + 1
        for band in "ABC":
            assert c[k] == band, (head, c[k])
            w = c[k + 1]
            m = re.fullmatch(r"([\d,]+) to ([\d,]+)", w) or re.fullmatch(r"([\d,]+) and over", w)
            lo = int(m.group(1).replace(",", ""))
            row = {"component": "toll", "min_kg": lo}
            if m.lastindex == 2:
                row["max_kg"] = int(m.group(2).replace(",", ""))
            row["euro"] = euro
            row["rate"] = float(c[k + 2].lstrip("£"))
            rows.append(row)
            k += 6
    tb = {
        "country": "GB", "currency": "GBP", "valid_from": valid_from, **({"valid_to": valid_to} if valid_to else {}),
        "name": "UK HGV road user levy (non-UK vehicles)",
        "law": "HGV Road User Levy Act 2013, section 6 and Schedule 1 (Tables 1, 1A and 1B) as amended: a non-UK HGV of 12,000 kg or more pays the daily rate for each day it uses a main road, by band of maximum permitted (revenue) weight of the combination and by whether it meets Euro 6. Rates as tabulated by the Department for Transport's guidance. Zero-emission HGVs are exempt. The table keeps the daily rate.",
        "sources": [{"title": "GOV.UK: How to use the HGV levy service (rates; a day runs from 00:00:00 to 23:59:59)", "url": "https://www.gov.uk/guidance/how-to-use-the-hgv-levy-service"},
                    {"title": "HGV Road User Levy Act 2013 (legislation.gov.uk)", "url": "https://www.legislation.gov.uk/ukpga/2013/7"}, *extra_sources],
        "vehicles": "Non-UK heavy goods vehicles of 12,000 kg or more (UK vehicles pay yearly or half-yearly with vehicle excise duty)",
        "min_kg": 12000,
        "tolled_roads": "Main roads: roads numbered with A or M, in England, Scotland, Wales and Northern Ireland.",
        "per_day": True,
        "day": "calendar",
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"gb-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")
    return valid_from


if __name__ == "__main__":
    main(*sys.argv[1:])
