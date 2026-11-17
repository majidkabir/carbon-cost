"""Builds Belarus's BelToll tables before 1 September 2026 from the
operator's announcements of each tariff change (beltoll.by news, fetched
as by-beltoll-<date>.html): each gives the Ministry of Transport and
Communications' decree, its start and the euro per km by axles. The
1 June 2023 tariffs give the table from 1 January 2024; each later one
starts on its own date (the last ends the day before resolution No. 42's
tariffs, 1 September 2026).

Usage: python3 build_by.py fetched/ out-dir"""
import datetime, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import by  # noqa: E402

PAGES = {"by-beltoll-2023-06-01": "https://beltoll.by/en/news/on-new-toll-tariffs-en",
         "by-beltoll-2024-09-20": "https://beltoll.by/en/news/on-new-toll-tarifffs-20-september-2024-en",
         "by-beltoll-2025-09-01": "https://beltoll.by/en/news/on-new-toll-rates-from-september-1-en"}
PAGES_94 = "https://beltoll.by/en/news/on-regulatory-documents-governing-the-use-of-toll-roads-en"
MONTHS = {m: i + 1 for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August",
                                          "September", "October", "November", "December"))}
DATE = r"(?:(\d{1,2}) ([A-Z][a-z]+),? (\d{4})|([A-Z][a-z]+) (\d{1,2}), (\d{4}))"
FIRST = "2024-01-01"


def date(g):
    d, m, y, m2, d2, y2 = g
    return datetime.date(int(y or y2), MONTHS[m or m2], int(d or d2))


def read(t):
    start = re.search(r"(?:Starting from|From) " + DATE + r", new (?:tariffs|rates)", t)
    decree = re.search(r"No\. (\d+) dated " + DATE + r"|dated " + DATE + r" No\. (\d+)", t)
    rates = re.search(r"2 axles (0[.,]\d{3}) 3 axles (0[.,]\d{3}) 4 (?:axles )?and more (0[.,]\d{3})", t)
    if not (start and decree and rates):
        return None
    g = decree.groups()
    no, when = (g[0], date(g[1:7])) if g[0] else (g[13], date(g[7:13]))
    return date(start.groups()), no, when, tuple(float(x.replace(",", ".")) for x in rates.groups())


def main(fetched, out):
    found = []
    for sid, url in PAGES.items():
        p = os.path.join(fetched, sid + ".html")
        if not os.path.exists(p):
            print(f"::warning title=build_by::{sid} not fetched")
            continue
        r = read(by.text(p))
        if not r:
            sys.exit(f"build_by: {sid}: the start, the decree or the rates not read")
        found.append(r + (url,))
    found.sort()
    # Resolution No. 94 replaced decree No. 21 from 11 December 2025 and kept its tariffs.
    kept = None
    p = os.path.join(fetched, "by-beltoll-2025-12-11.html")
    if os.path.exists(p):
        m = re.search(r"Resolution No\. (\d+) dated (\d+ [A-Z][a-z]+ \d{4}) .{0,80}?enters into force on (\d+ [A-Z][a-z]+ \d{4})\. .{0,400}?the tariffs, .{0,200}?remain unchanged", by.text(p))
        if not m:
            sys.exit("build_by: by-beltoll-2025-12-11: the note on resolution No. 94 not read")
        kept = (m.group(1), m.group(2), m.group(3))
    for i, (start, no, when, rates, url) in enumerate(found):
        end = found[i + 1][0] - datetime.timedelta(days=1) if i + 1 < len(found) else datetime.date(2026, 8, 31)
        frm = max(start.isoformat(), FIRST)
        law = (f"Decree of the Ministry of Transport and Communications No. {no} of {when} (amending its decree No. 21 of 17 June 2013), "
               f"in force from {start}: EUR {rates[0]} per km for vehicles over 3.5 t with 2 axles, {rates[1]} with 3, {rates[2]} with 4 or more, "
               "as BelToll announced them; BelToll counts the axles of the vehicle with its trailers. "
               "Toll roads: the list of the Regulation approved by Council of Ministers resolution No. 340 of 30 April 2013, "
               "placed on the ways OpenStreetMap tags as toll roads.")
        srcs = [{"title": f"BelToll: new tariffs from {start} (decree No. {no})", "url": url}]
        if kept and i == len(found) - 1:
            law += f" Resolution No. {kept[0]} of {kept[1]}, in force from {kept[2]}, replaced decree No. 21 and kept these tariffs (BelToll)."
            srcs.append({"title": f"BelToll: the regulatory documents (resolution No. {kept[0]}, the tariffs unchanged)", "url": PAGES_94})
        t = by.table(frm, rates, law, srcs)
        t["valid_to"] = end.isoformat()
        by.write(out, t)


if __name__ == "__main__":
    main(*sys.argv[1:])
