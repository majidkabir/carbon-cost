"""Builds the Romanian TollRo rate table from CNAIR's active pricing
offer (fetch.py's ro-active-pricing-offer-*.json, the JSON the eToll
TollRo page's tariff widget shows).

Usage: python3 ro.py fetched/ out-dir -> out-dir/ro-<date>.json

The offer lists a price in lei/km including 21% VAT for each vehicle
category (I over 3.5 to 7.5 t, II over 7.5 to under 12 t, III 12 t and
over), road category (001 motorways and expressways, 002 national roads)
and emission class (Euro 0 to Euro 6, Electric). EURO classes with the
same price share a row; Electric is CO2 class 5. The order's date is
read from the offer's name ("OMTI 959/2026 din 08.10.2026").
"""
import glob, json, os, re, sys

VAT = 1.21
CATS = {"I": {"min_kg": 3501, "max_kg": 7500}, "II": {"min_kg": 7501, "max_kg": 11999}, "III": {"min_kg": 12000}}
ROADS = {"001": "motorway", "002": "other"}


def main(fetched, out):
    offer = None
    for f in sorted(glob.glob(os.path.join(fetched, "ro-active-pricing-offer-*.json"))):
        try:
            d = json.load(open(f))
        except ValueError:
            continue
        if d.get("productPriceList"):
            offer = d
            break
    if offer is None:
        sys.exit("no pricing offer in " + fetched)
    m = re.search(r"OMTI\s+(\d+)/(\d{4})\s+din\s+(\d\d)\.(\d\d)\.(\d{4})", offer["name"])
    order, valid_from = f"{m.group(1)}/{m.group(2)}", f"{m.group(5)}-{m.group(4)}-{m.group(3)}"
    assert offer["currency"]["code"] == "RON"
    price = {}
    for p in offer["productPriceList"]:
        k = p.get("tollableKmProduct")
        if not k:
            continue
        e = k["emissionStandardsCategory"]["name"]
        price[(k["vehicleCategory"]["name"], k["tollableRoadCategory"]["code"], "zev" if e == "Electric" else int(e.split()[-1]))] = p["price"]
    rows = []
    for cat, mass in CATS.items():
        for code, road in ROADS.items():
            rows.append({"component": "toll", "road": road, **mass, "co2_class": [5], "rate": round(price[(cat, code, "zev")] / VAT, 4)})
            groups = []
            for e in range(6, -1, -1):
                if groups and price[(cat, code, groups[-1][0])] == price[(cat, code, e)]:
                    groups[-1].append(e)
                else:
                    groups.append([e])
            for g in groups:
                rows.append({"component": "toll", "road": road, **mass, "euro": sorted(g), "rate": round(price[(cat, code, g[0])] / VAT, 4)})
    t = {
        "country": "RO", "currency": "RON", "valid_from": valid_from, "valid_to": f"{m.group(5)}-12-31",
        "name": "Romanian distance toll (TollRo)",
        "law": "Legea nr. 226/2023: TollRo is the unit rate times the km driven on the SETRE România network. Unit rates in lei/km including 21% VAT from Ordinul MTI nr. 1.925/2025 (Monitorul Oficial nr. 940/2025) as replaced by Ordinul MTI nr. "
               + f"{order} of {int(m.group(3))} {['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][int(m.group(4))]} {m.group(5)}"
               + ": by maximum authorised mass (I over 3.5 to 7.5 t, II over 7.5 to under 12 t, III 12 t and over), road category (motorways and expressways, or national roads) and EURO class, with electric trucks at 25% of the EURO VI rate. One rate including the infrastructure and air-pollution parts. Rates here exclude VAT (divided by 1.21). Updated each 1 January by consumer prices.",
        "sources": [{"title": f"CNAIR eToll: TollRo rates in force (OMTI {order})", "url": "https://portal.etoll.ro/web/guest/tollro"},
                    {"title": "Ordinul MTI nr. 1.925/2025 (Portal Legislativ)", "url": "https://legislatie.just.ro/Public/DetaliiDocument/302972"},
                    {"title": "Legea nr. 226/2023 (CNAIR eToll, acte normative)", "url": "https://portal.etoll.ro/web/guest/acte-normative"}],
        "vehicles": "Goods vehicles over 3.5 t maximum authorised mass", "min_kg": 3501,
        "tolled_roads": "National roads, expressways and motorways run by CNAIR, except national roads inside municipalities (between the town entry and exit signs). County and local roads aren't tolled.",
        "motorway_share": 1,
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ro-{valid_from}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows from", offer["name"])


if __name__ == "__main__":
    main(*sys.argv[1:])
