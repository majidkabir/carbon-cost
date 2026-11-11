"""Builds the Storebælt and Øresund bridge table from the operators'
business price pages (fetch.py's dk-storebaelt.html and dk-oresund.html).

Usage: python3 dk_bridges.py fetched/ out-dir -> out-dir/dk-bridges-<year>-01-01.json

Storebælt ("Priser for erhverv <year>", DKK including 25% VAT): trucks
up to 10 m, 10-20 m and over 20 m (up to bridge class 100), the
Eksprespris; the Grøn rabat percent from "spare N%". Øresund (DKK
excluding 25% VAT): the normal price in the payment plant and the
ØresundBUSINESS price for the first band of crossings, for vans of
6-9 m and for vehicles over 9 m.

The toll plazas' places are OpenStreetMap's (Storebælt toll booths at
Sprogø-Halsskov, Øresund bridge at Lernacken), fixed here.
"""
import html, json, os, re, sys


def text(path):
    t = html.unescape(open(path, encoding="utf-8", errors="replace").read())
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def kr(s):
    return int(s.replace(".", ""))


def main(fetched, out):
    sb = text(os.path.join(fetched, "dk-storebaelt.html"))
    # Until 2025 the page read "Prisliste <year>" with the list price, then
    # the green price; from 2026 "Priser for erhverv <year>" with the green
    # price, then the Eksprespris.
    new = re.search(r"Priser for erhverv (\d{4})", sb)
    year = (new or re.search(r"Prisliste (\d{4})", sb)).group(1)
    assert "inkl. 25 % moms" in sb
    p = {}
    last = "Lastbil over 20 m og op til broklasse 100" if new else "Lastbil over 20 m og op til 100 t"
    for label, key in (("Lastbil op til 10 m", "up to 10 m"), ("Lastbil 10-20 m", "10-20 m"), (last, "over 20 m")):
        m = re.search(re.escape(label) + r"(?: \d)? ([\d.]+) kr\. ([\d.]+) kr\.", sb)
        green, price = (kr(m.group(1)), kr(m.group(2))) if new else (kr(m.group(2)), kr(m.group(1)))
        p[key] = price / 1.25
        p[key + " green"] = green
    pct = int(re.search(r"spare (\d+) ?% på turen over Storebæltsbroen", sb).group(1))
    for k in ("up to 10 m", "10-20 m", "over 20 m"):
        # The green price on the page is the express price less the discount.
        assert abs(p[k] * 1.25 * (1 - pct / 100) - p[k + " green"]) <= 1, k
    ob = text(os.path.join(fetched, "dk-oresund.html"))
    # Until 2025: "eksklusiv moms", prices without "DKK", "(över 9m)".
    assert "eksklusiv 25% moms" in ob or "Priserne er pr. tur og eksklusiv moms" in ob
    van = re.search(r"Varebil \(6-9m\) 1-\d+ (\d+)(?: DKK)? (\d+)(?: DKK)?", ob)
    truck = re.search(r"Lastbil, Varebil \([oö]ver 9m\) 1-\d+ (\d+)(?: DKK)? (\d+)(?: DKK)?", ob)
    first_van = re.search(r"Varebil \(6-9m\) 1-(\d+)", ob).group(1)
    first_truck = re.search(r"Lastbil, Varebil \([oö]ver 9m\) 1-(\d+)", ob).group(1)
    t = {
        "country": "DK", "currency": "DKK", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True,
        "name": "Storebælt and Øresund bridge tolls",
        "law": f"Fixed price per crossing by vehicle length, on top of the km-based vejafgift: Storebælt (A/S Storebælt) and Øresund (Øresundsbro Konsortiet) price lists for {year}.",
        "sources": [{"title": f"Storebælt: prices for business customers {year}", "url": "https://storebaelt.dk/priser-rabatter/erhverv/"},
                    {"title": "Øresundsbron: prices for trucks and vans (business)", "url": "https://www.oresundsbron.com/da/erhverv/lastbil"}],
        "vehicles": "Vehicles over 3.5 t, by length", "min_kg": 3501,
        "tolled_roads": "The Storebælt bridge (E20 Funen-Zealand) and the Øresund bridge (E20 Copenhagen-Malmö).",
        "closed_systems": [
            {"name": "Storebælt bridge",
             "law": f"Storebæltsforbindelsen: prices set by the transport minister (lov om Sund & Bælt Holding A/S); A/S Storebælt's business price list {year}, DKK including 25% VAT, here excluding it. Green discount (Grøn rabat) {pct}% for EURO VI and electric or hydrogen trucks on a Storebælt Erhverv agreement paying automatically.",
             "groups": [{"name": "up to 10 m", "min_kg": 3501, "min_length_m": 0, "max_length_m": 10},
                        {"name": "10-20 m", "min_kg": 3501, "min_length_m": 10, "max_length_m": 20},
                        {"name": "over 20 m", "min_kg": 3501, "min_length_m": 20}],
             "stations": [{"name": "Storebælt", "points": [{"name": "booth", "lat": 55.34993, "lon": 11.10876}, {"name": "booth", "lat": 55.34967, "lon": 11.10882}]}],
             "prices": {"Storebælt|Storebælt": {k: round(p[k], 2) for k in ("up to 10 m", "10-20 m", "over 20 m")}},
             "discounts": [{"name": "Grøn rabat", "etc": True, "euro": [6], "co2_class": [5], "percent": pct}]},
            {"name": "Øresund bridge",
             "law": f"Øresundsbron: Øresundsbro Konsortiet's business prices per crossing, DKK excluding 25% VAT; with ØresundBUSINESS (etc) the price for the first {int(first_truck):,} crossings a year by a truck over 9 m ({truck.group(1)} DKK) or the first {int(first_van):,} by a van of 6-9 m ({van.group(1)} DKK).",
             "groups": [{"name": "up to 9 m", "min_kg": 3501, "max_length_m": 9}, {"name": "over 9 m", "min_kg": 3501, "min_length_m": 9}],
             "stations": [{"name": "Øresundsbron", "points": [{"name": "bridge", "lat": 55.57047, "lon": 12.84879}, {"name": "bridge", "lat": 55.57027, "lon": 12.84989}]}],
             "prices": {"Øresundsbron|Øresundsbron": {"up to 9 m": int(van.group(2)), "over 9 m": int(truck.group(2))}},
             "etc_prices": {"Øresundsbron|Øresundsbron": {"up to 9 m": int(van.group(1)), "over 9 m": int(truck.group(1))}}},
        ],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"dk-bridges-{year}-01-01.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
