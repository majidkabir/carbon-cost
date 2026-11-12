"""Builds the UK HGV levy tables of earlier years with tools/tables/gb.py
from GOV.UK's guidance "How to use the HGV levy service" as the Internet
Archive kept it (tools/history/sources.json: gb-levy-guide-<yyyy-mm>).

Those copies don't say "Levy rates from"; the page's own update history
dates the rates: "1 August 2023 First published" (the reformed levy) and
"1 April 2025 Levy rates increased in line with UK inflation". A copy's
rates start at its latest such entry; a table ends the day before the
next one starts (the current table, from 1 April 2026, is in rates/data).

Usage: python3 build_gb.py fetched/ out-dir
"""
import datetime, html, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tables"))
import gb  # noqa: E402

COPIES = [("gb-levy-guide-2024-06.html", "20240615000000"), ("gb-levy-guide-2025-06.html", "20250615000000")]
CURRENT = "2026-04-01"


def rates_start(path):
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", open(path, encoding="utf-8").read())))
    days = [m.group(1) for m in re.finditer(r"(\d{1,2} \w+ \d{4}) (?:Levy rates|First published)", t)]
    assert days, path
    d = [datetime.datetime.strptime(x, "%d %B %Y").date() for x in days]
    return max(d).isoformat()


def main(fetched, out):
    found = [(n, ts, rates_start(os.path.join(fetched, n))) for n, ts in COPIES if os.path.exists(os.path.join(fetched, n))]
    found.sort(key=lambda x: x[2])
    for i, (name, ts, frm) in enumerate(found):
        nxt = found[i + 1][2] if i + 1 < len(found) else CURRENT
        end = (datetime.date.fromisoformat(nxt) - datetime.timedelta(days=1)).isoformat()
        url = f"https://web.archive.org/web/{ts}/https://www.gov.uk/guidance/how-to-use-the-hgv-levy-service"
        gb.main(fetched, out, name, extra_sources=[{"title": f"The guidance as archived by the Internet Archive ({ts[:8]})", "url": url}],
                valid_to=end, valid_from=frm)


if __name__ == "__main__":
    main(*sys.argv[1:])
