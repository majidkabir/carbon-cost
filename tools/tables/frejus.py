"""Builds the Fréjus road tunnel table from SFTRF's price list for the
French platform (fetch.py's fr-frejus-tunnel.pdf, as pdftotext -layout
text: fr-frejus-tunnel.txt).

Usage: python3 frejus.py fetched/ out-dir -> out-dir/frejus-<date>.json

Class 3 (two axles, over 3 m) and class 4 (three axles or more, over 3 m)
one-way prices ("Course simple"), EUR including 20% VAT, on the rows
for trucks ("PL Euro 5-6"): the list has no truck price for older EURO
classes. The date is the list's "Tarifs au dd/mm/yyyy". The plaza's
place is OpenStreetMap's (the SFTRF toll booths at the French portal).
"""
import json, os, re, sys

VAT = 1.20


def main(fetched, out):
    text = open(os.path.join(fetched, "fr-frejus-tunnel.txt"), encoding="utf-8").read()
    d = re.search(r"Tarifs au (\d\d)/(\d\d)/(\d{4})", text)
    valid_from = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
    price = {}
    for cls in ("3", "4"):
        m = re.search(r"Classe " + cls + r"\s+([\d ]+,\d\d)\s+([\d ]+,\d\d)\s+PL Euro 5-6", text)
        price[cls] = round(float(m.group(1).replace(" ", "").replace(",", ".")) / VAT, 2)
    t = {
        "country": "FR", "currency": "EUR", "valid_from": valid_from, "valid_to": f"{d.group(3)}-12-31", "crossings": True,
        "name": "Fréjus road tunnel toll",
        "law": f"Tunnel routier du Fréjus: SFTRF's prices on the French platform from {valid_from}, one way, EUR including 20% VAT, here excluding it; class 3 (two axles) and 4 (three or more), over 3 m high. Truck prices are given for EURO 5 and 6.",
        "sources": [{"title": f"SFTRF: Fréjus tunnel prices from {valid_from} (French platform)", "url": "https://www.sftrf.fr/tarifs-tunnel/"}],
        "vehicles": "Vehicles over 3.5 t", "min_kg": 3501,
        "tolled_roads": "The Fréjus road tunnel (T4, Modane-Bardonecchia), priced at the French platform's one-way price whichever the direction.",
        "closed_systems": [{
            "name": "Fréjus road tunnel",
            "law": "SFTRF price list for the French platform, one way (course simple), EUR including 20% VAT, here excluding it.",
            "groups": [{"name": "3", "min_kg": 3501, "max_axles": 2}, {"name": "4", "min_kg": 3501, "min_axles": 3}],
            "stations": [{"name": "Tunnel du Fréjus", "points": [{"name": "toll plaza", "lat": 45.19439, "lon": 6.67415}]}],
            "prices": {"Tunnel du Fréjus|Tunnel du Fréjus": price},
        }],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"frejus-{valid_from}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, price)


if __name__ == "__main__":
    main(*sys.argv[1:])
