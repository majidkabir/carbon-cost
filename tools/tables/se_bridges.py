"""Builds the Swedish bridge infrastructure charge table: the charges per
passage from Transportstyrelsen's page for each bridge (fetch.py's
se-broavgift-<bridge>.html) and the charging stations (betalstationer)
from OpenStreetMap (the workflow's se-osm.geojsonseq: toll gantries
named after the bridges, from Geofabrik's Sweden extract; its date in
se-osm-timestamp.txt).

Usage: python3 se_bridges.py fetched/ out-dir -> out-dir/se-bridges-<date>.json

Förordning (2014:1564) om infrastrukturavgifter på väg 4 § charges the
use of the bridges over Motalaviken (road 50), Sundsvallsfjärden (E4)
and Skurusundet (road 222). Each page gives the amount per passage
("kronor per passagetillfälle"): for heavy trucks (total weight over
3.5 t) where it names them, else the one amount for all vehicles. Each
bridge's charging station is the OSM toll gantries with its name, the
gantries within 1.5 km making one point; a passage either way pays. The
table is valid from the date Förordning (2024:194), which lists the three
bridges in 4 §, came into force; the amounts are those published now.
"""
import html, json, math, os, re, sys

BRIDGES = [("motala", "Motalabron"), ("sundsvall", "Sundsvallsbron"), ("skurubron", "Skurubron")]


def lines(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<(p|li|h\d|div|br)[^>]*>", "\n", t)
    return [re.sub(r"\s+", " ", x).strip() for x in html.unescape(re.sub(r"<[^>]+>", "", t)).split("\n") if x.strip()]


def main(fetched, out):
    gantries = {}
    for line in open(os.path.join(fetched, "se-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("highway") == "toll_gantry" and g["type"] == "Point" and p.get("name"):
            gantries.setdefault(p["name"], []).append(g["coordinates"])
    osm = open(os.path.join(fetched, "se-osm-timestamp.txt")).read().strip()[:10]
    # In force since the förordning's amendment that lists the three bridges.
    law = open(os.path.join(fetched, "se-2014-1564.html"), encoding="utf-8").read()
    m = re.search(r"2024:194\s+1\. Denna förordning träder i kraft den (\d+) (\w+) (\d{4})", law)
    months = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"]
    date = f"{m.group(3)}-{months.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
    points = []
    for sid, name in BRIDGES:
        c = lines(os.path.join(fetched, f"se-broavgift-{sid}.html"))
        amounts = [x for x in c if re.match(r"\d+ kronor per passagetillfälle", x)]
        heavy = [x for x in amounts if "tunga lastbilar" in x]
        pick = heavy or amounts
        if len(pick) != 1:
            sys.exit(f"{sid}: amounts {amounts}")
        rate = int(re.match(r"(\d+) kronor", pick[0]).group(1))
        gs = gantries.get(name, [])
        if not gs:
            sys.exit(f"{name}: no toll gantries in OpenStreetMap")
        lon, lat = sum(x[0] for x in gs) / len(gs), sum(x[1] for x in gs) / len(gs)
        if max(math.hypot((x[0] - lon) * 111.2 * math.cos(math.radians(lat)), (x[1] - lat) * 111.2) for x in gs) > 1.5:
            sys.exit(f"{name}: gantries more than 1.5 km apart: {gs}")
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": rate})
        print(f"{name}: {rate} kr at {lat:.5f},{lon:.5f} ({len(gs)} gantries); {pick[0]}")
    tb = {
        "country": "SE", "currency": "SEK", "valid_from": date,
        "name": "Swedish bridge infrastructure charges (broavgift)",
        "law": "Lag (2024:172) om infrastrukturavgifter på väg; Förordning (2014:1564) 4 §: a charge per passage of the bridges over Motalaviken, Sundsvallsfjärden and Skurusundet, at the amounts Transportstyrelsen publishes (heavy trucks over 3.5 t where they differ). Charged at each bridge's charging station (OpenStreetMap toll gantries), either direction. Swedish and foreign vehicles alike.",
        "sources": [{"title": "Transportstyrelsen: Broavgift på Motalabron", "url": "https://www.transportstyrelsen.se/sv/vagtrafik/fordon/skatter-och-avgifter/infrastrukturavgift/broavgift-motala/"},
                    {"title": "Transportstyrelsen: Broavgift på Sundsvallsbron", "url": "https://www.transportstyrelsen.se/sv/vagtrafik/fordon/skatter-och-avgifter/infrastrukturavgift/broavgift-sundsvall/"},
                    {"title": "Transportstyrelsen: Broavgift på Skurubron", "url": "https://www.transportstyrelsen.se/sv/vagtrafik/fordon/skatter-och-avgifter/infrastrukturavgift/broavgift-skurubron/"},
                    {"title": "Förordning (2014:1564), consolidated (Riksdagen)", "url": "https://data.riksdagen.se/dokument/sfs-2014-1564.text"}],
        "vehicles": "Trucks over 3.5 t",
        "min_kg": 3501,
        "tolled_roads": "Motalabron (road 50), Sundsvallsbron (E4) and Skurubron (road 222).",
        "crossings": True,
        "point_match_km": 0.15,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"se-bridges-{date}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
