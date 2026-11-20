"""Builds the statements that a country levies no road charge on trucks
(ORCT 6.13, no_charge): no road toll, user charge (vignette) or other
charge for using its roads, as the country's own authority states it. A
country whose only tolls are a tunnel's or a bridge's (crossings, priced
on their own) says so in its statement.

Each statement is read from the authority's page as fetch.py fetched it
(<id>.html), or else from the copy read in Chrome (browser/<id>.txt); the
builder fails for a country whose page no longer says it.

Usage: python3 no_charge.py fetched/ out-dir -> out-dir/nocharge-<cc>-<date>.json
"""
import html, json, os, re, sys

BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")

# id: the source (sources.json, browser/<id>.txt); start: the day the page was
# first read (it gives no date from which the statement holds); says: what
# the page must say (a regular expression over its text, spaces collapsed).
COUNTRIES = [
    {"id": "fi-traficom", "country": "FI", "currency": "EUR", "start": "2026-11-20",
     "says": r"Time-based road user charges \(vignettes\), distance-based road tolls and vehicle emission stickers are not used in Finland\.",
     "title": "Traficom (Finnish Transport and Communications Agency): Vehicle tax",
     "url": "https://www.traficom.fi/en/drivers-and-vehicles/vehicle-taxation/vehicle-tax",
     "name": "Finland: no road toll or vignette",
     "law": ("Traficom, the agency that collects Finland's vehicle tax, states on its vehicle tax page that time-based road user "
             "charges (vignettes), distance-based road tolls and vehicle emission stickers are not used in Finland. Vehicles "
             "registered in Finland pay the yearly vehicle tax instead, not a charge for using the roads (not modelled). The page "
             "gives no date from which this holds: valid_from is the day it was first read."),
     "no_charge": "no road toll, vignette or emission sticker for trucks (Traficom: they are not used in Finland)."},
]


def text(fetched, c):
    p = os.path.join(fetched, c["id"] + ".html")
    if os.path.exists(p):
        raw = open(p, encoding="utf-8", errors="replace").read()
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S))))
        if re.search(c["says"], t):
            return t, "fetched"
    p = os.path.join(BROWSER, c["id"] + ".txt")
    print(f"{c['id']}: the copy read in Chrome")
    return re.sub(r"\s+", " ", " ".join(l for l in open(p, encoding="utf-8") if not l.startswith("# "))), "browser"


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    failed = []
    for c in COUNTRIES:
        t, how = text(fetched, c)
        if not re.search(c["says"], t):
            print(f"{c['country']}: {c['id']} no longer says it")
            failed.append(c["country"])
            continue
        tb = {"country": c["country"], "currency": c["currency"], "valid_from": c["start"], "name": c["name"], "law": c["law"],
              "sources": [{"title": c["title"] + (f" (read in Chrome: tools/tables/browser/{c['id']}.txt)" if how == "browser" else ""),
                           "url": c["url"]}],
              "vehicles": "All vehicles", "no_charge": c["no_charge"]}
        path = os.path.join(out, f"nocharge-{c['country'].lower()}-{c['start']}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path)
    if failed:
        sys.exit("no statement for " + ", ".join(failed))


if __name__ == "__main__":
    main(*sys.argv[1:])
