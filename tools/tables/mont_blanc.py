"""Builds the Mont Blanc tunnel table from ATMB's price page for heavy
vehicles (fetch.py's fr-mont-blanc-tunnel.html).

Usage: python3 mont_blanc.py fetched/ out-dir -> out-dir/mont-blanc-<date>.json

The one-way price ("Prix pour un aller simple") of class 3 (two axles)
and class 4 (three or more) in the France–Italy direction, EUR including
20% VAT ("TVA 20% incluse"), here excluding it. The Italy–France price
is the same before VAT (it includes Italy's 22%): the check below holds
it to within 0.1 EUR. Trucks of EURO 0 to 4 aren't admitted. The
plaza's place is OpenStreetMap's (ATMB's booths at the French portal).
"""
import html, json, os, re, sys

MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def main(fetched, out):
    t = html.unescape(open(os.path.join(fetched, "fr-mont-blanc-tunnel.html"), encoding="utf-8").read())
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)))
    d = re.search(r"Au (\d+)(?:er)? (\w+) (\d{4}) \(TVA 20% incluse\)", t)
    valid_from = f"{d.group(3)}-{MONTHS[d.group(2).lower()]:02d}-{int(d.group(1)):02d}"
    fr_it, it_fr = t.index("Dans le sens France – Italie"), t.index("Dans le sens Italie – France")
    price = {}
    for cls in ("3", "4"):
        a = num(re.search(r"Classe " + cls + r" [^€]*? ([\d ]+,\d\d) €", t[fr_it:it_fr]).group(1))
        b = num(re.search(r"Classe " + cls + r" [^€]*? ([\d ]+,\d\d) €", t[it_fr:]).group(1))
        assert abs(a / 1.20 - b / 1.22) < 0.1, (cls, a, b)
        price[cls] = round(a / 1.20, 2)
    ban = re.search(r"interdit aux véhicules de transport de marchandises[^.]*Euro 0, Euro 1 et Euro 2", t)
    tb = {
        "country": "FR", "currency": "EUR", "valid_from": valid_from, "valid_to": f"{d.group(3)}-12-31", "crossings": True,
        "name": "Mont Blanc tunnel toll",
        "law": f"Tunnel du Mont Blanc (TMB-GEIE): ATMB's prices for heavy vehicles from {valid_from}, one way, France to Italy, EUR including 20% VAT, here excluding it; class 3 (two axles) and 4 (three or more). The Italy to France price is the same before Italy's 22% VAT. Goods vehicles over 3.5 t of EURO 0 to 4 aren't admitted.",
        "sources": [{"title": f"ATMB: Mont Blanc tunnel prices for heavy vehicles from {valid_from}", "url": "https://www.atmb.com/telepeage-tarifs/les-tarifs-au-tunnel-du-mont-blanc-pour-les-poids-lourds/"}],
        "vehicles": "Vehicles over 3.5 t", "min_kg": 3501,
        "tolled_roads": "The Mont Blanc tunnel (Chamonix-Courmayeur), priced when the route passes the French plaza, whichever the direction.",
        "closed_systems": [{
            "name": "Mont Blanc tunnel",
            "law": "ATMB/TMB-GEIE price for heavy vehicles, one way, EUR including 20% VAT, here excluding it.",
            "groups": [{"name": "3", "min_kg": 3501, "max_axles": 2}, {"name": "4", "min_kg": 3501, "min_axles": 3}],
            "stations": [{"name": "Tunnel du Mont Blanc", "points": [{"name": "toll plaza", "lat": 45.90100, "lon": 6.86072}]}],
            "prices": {"Tunnel du Mont Blanc|Tunnel du Mont Blanc": price},
        }],
    }
    assert ban, "the EURO ban sentence moved"
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"mont-blanc-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, price)


if __name__ == "__main__":
    main(*sys.argv[1:])
