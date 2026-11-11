"""Builds the national CO2 prices on road fuel (rates/data/fuelco2-*.json)
from the fetched law texts (sources.json, table fuelco2-*):

- Germany, BEHG § 10 (2): the fixed certificate price of 2024 and 2025,
  and for 2026 the corridor of 55 to 65 euro; the 2026 price is the
  auctions' clearing price, 65 euro when every auction applied the
  "65 EUR rule" (BEHV § 12 (4): more volume allotted because the price
  reached the ceiling), read from EEX's auction calendar;
- Austria, NEHG 2022 § 10 (1): the certificate value by calendar year
  (to 2025; the law sets none for later years).

Usage: python3 fuel_co2.py fetched/ out-dir"""
import html, json, os, re, sys


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def src(srcs, sid):
    return {"title": srcs[sid]["what"], "url": srcs[sid]["url"]}


def write(out, f):
    path = os.path.join(out, f"fuelco2-{f['country'].lower()}-{f['valid_from']}.json")
    json.dump(f, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, f["rate_per_t"])


def germany(fetched, out, srcs):
    t = text(os.path.join(fetched, "de-behg-10.html"))
    for y in (2024, 2025):
        m = re.search(rf"im Zeitraum vom 1\. Januar {y} bis zum 31\. Dezember {y}: (\d+) Euro", t)
        if not m:
            sys.exit(f"BEHG § 10: no fixed price for {y}")
        write(out, {"country": "DE", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": float(m.group(1)),
                    "law": f"BEHG § 10 (2): fixed price of {m.group(1)} euro per certificate (one tonne of CO2) in {y}. Fuel suppliers buy a certificate for each tonne of CO2 their fuel emits and pass the cost on in the fuel price.",
                    "sources": [src(srcs, "de-behg-10")]})
    m = re.search(r"Für das Jahr 2026 wird ein Preiskorridor mit einem Mindestpreis von (\d+) Euro pro Emissionszertifikat und einem Höchstpreis von (\d+) Euro", t)
    if not m:
        sys.exit("BEHG § 10: no 2026 price corridor")
    lo, hi = float(m.group(1)), float(m.group(2))
    rows = []
    for line in open(os.path.join(fetched, "de-eex-nehs-auctions.csv"), encoding="utf-8-sig").read().splitlines()[1:]:
        f = line.split(";")
        if len(f) > 5 and f[3] == "2026":
            rows.append((f[0], float(f[4]), int(f[5])))
    if not rows or any(not lo <= p <= hi for _, p, _ in rows):
        sys.exit(f"EEX: no 2026 auctions in the corridor ({rows[:3]})")
    vol = sum(v for _, _, v in rows)
    avg = round(sum(p * v for _, p, v in rows) / vol, 2)
    prices = sorted({p for _, p, _ in rows})
    write(out, {"country": "DE", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": avg,
                "law": f"BEHG § 10 (2): 2026 certificates are auctioned in a corridor of {m.group(1)} to {m.group(2)} euro. This is the volume-weighted clearing price of the {len(rows)} auctions EEX held ({rows[-1][0]} to {rows[0][0]}; clearing prices {', '.join(f'{p:g}' for p in prices)} euro). Certificates bought after the auctions cost 68 euro (the excess quantity price), so a supplier's average may be a little higher.",
                "sources": [src(srcs, "de-behg-10"), src(srcs, "de-eex-nehs-auctions")]})


def austria(fetched, out, srcs):
    t = text(os.path.join(fetched, "at-nehg.html"))
    m = re.search(r"Die nationalen Emissionszertifikate haben einen Ausgabewert von: ?Kalenderjahr ?Betrag (.*?) \(2\)", t)
    if not m:
        sys.exit("NEHG 2022 § 10 (1) not found")
    vals = dict(re.findall(r"(20\d\d) (\d+(?:,\d+)?) Euro", m.group(1)))
    for y in ("2024", "2025"):
        if y not in vals:
            sys.exit(f"NEHG 2022 § 10 (1): no value for {y}")
        write(out, {"country": "AT", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Nationaler Emissionszertifikatehandel certificate value", "rate_per_t": float(vals[y].replace(",", ".")),
                    "law": f"NEHG 2022 § 10 (1): certificate value of {vals[y]} euro per tonne of CO2 in {y}. Fuel suppliers pay it for the CO2 their fuel emits and pass it on in the fuel price. The law sets no value for 2026 or later, so those years aren't priced.",
                    "sources": [src(srcs, "at-nehg")]})


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    srcs = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json"), encoding="utf-8"))["sources"]}
    germany(fetched, out, srcs)
    austria(fetched, out, srcs)


if __name__ == "__main__":
    main(*sys.argv[1:])
