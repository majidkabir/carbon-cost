"""Builds the Swedish congestion tax tables (trängselskatt, Stockholm and
Göteborg) from Lag (2004:629) om trängselskatt as consolidated by the
Riksdag (fetch.py's se-2004-629.html, the .text form) and the charging
stations (betalstationer) in OpenStreetMap (the workflow's
se-osm.geojsonseq: Transportstyrelsen's toll gantries, from Geofabrik's
Sweden extract).

Usage: python3 se_congestion.py fetched/ out-dir
       -> out-dir/se-congestion-stockholm-<date>.json, se-congestion-goteborg-<date>.json

Bilaga 1 (Stockholm, the version in force, not the one awaiting the
government's date) gives the amounts per passage by time of day for the
inner city and for Essingeleden, in low and high season; bilaga 2
(Göteborg) one schedule. The rules the tables carry are read from the same
text and checked: the high season (1 March to the day before Midsummer
Eve, 15 August to 30 November), the daily caps, July (Stockholm: only
its first five weekdays; Göteborg: none), the eves of public holidays
Stockholm still taxes, and Göteborg's 60-minute rule. The cost code
applies them for the trip's date and time (Request.Time).

Stations: OSM toll gantries operated by Transportstyrelsen, in Stockholm
or Göteborg by their website link; the gantries named "Essingeleden" take
the Essingeleden schedule. Göteborg's Backa stations (bilaga 2 point 5:
Södra Tagenevägen, Skälltorpsvägen, Backadalen, Tingstadsmotet avfart
E6, Tingstadsvägen) are taxed only with a control point passed within 30
minutes; they're left out. A passage either way pays. Valid from the
date Lag (2018:200), which set these amounts, came into force.
"""
import json, os, re, sys

MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"]
BACKA = {"Södra Tagenevägen", "Skälltorpsvägen", "Backadalen", "Tingstadsmotet avfart E6", "Tingstadsvägen"}


def schedule(block, high):
    out = []
    for m in re.finditer(r"^(\d{1,2})\.(\d\d)-(\d{1,2})\.(\d\d)\s+(\d+)(?:\s+(\d+))?\s*$", block, flags=re.M):
        w = {"from": f"{int(m.group(1)):02d}:{m.group(2)}", "to": f"{int(m.group(3)):02d}:{m.group(4)}", "amount": int(m.group(5))}
        if high:
            w["high"] = int(m.group(6))
        out.append(w)
    if len(out) < 5:
        sys.exit(f"schedule: {len(out)} rows")
    return out


def need(text, phrase, what):
    if re.sub(r"\s+", " ", phrase) not in re.sub(r"\s+", " ", text):
        sys.exit(f"{what}: the law no longer says {phrase!r}")


def main(fetched, out):
    t = open(os.path.join(fetched, "se-2004-629.html"), encoding="utf-8").read().replace("\r", "")
    s1 = t.index("Bilaga 1 /Upphör att gälla")
    s2 = t.index("Bilaga 1 /Träder i kraft")
    b1, b2 = t[s1:s2], t[t.index("Bilaga 2", s2):]
    inner = schedule(b1[b1.index("Stockholms innerstad\n\nTider"):b1.index("Essingeleden\n\nTider")], True)
    essinge = schedule(b1[b1.index("Essingeleden\n\nTider"):b1.index("3. Den sammanlagda")], True)
    gbg = schedule(b2[b2.index("Tider"):b2.index("3. Skatt betalas inte")], False)
    # The version awaiting its date has the same amounts.
    pend = t[s2:t.index("Bilaga 2", s2)]
    if schedule(pend[pend.index("Stockholms innerstad\n\nTider"):pend.index("Essingeleden\n\nTider")], True) != inner:
        sys.exit("Stockholm: the pending bilaga 1 changes the amounts")
    m = re.search(r"högst\s+uppgå till (\d+) kronor under lågsäsong och (\d+) kronor under\s+högsäsong", b1)
    cap, cap_high = int(m.group(1)), int(m.group(2))
    cap_gbg = int(re.search(r"högst\s+uppgå till (\d+) kr", b2).group(1))
    need(b1, "Med högsäsong avses 1 mars-dagen före midsommarafton och 15 augusti-30 november", "Stockholm")
    need(b1, "- dag före långfredagen,", "Stockholm")
    need(b1, "- dag före Kristi himmelsfärdsdag, och", "Stockholm")
    need(b1, "- dag före alla helgons dag.", "Stockholm")
    need(b1, "- dag före första maj och", "Stockholm")
    need(b1, "- dag före nationaldagen.", "Stockholm")
    need(b1, "Under juli månad ska ingen skatt tas ut förutom för de fem första vardagarna utom lördag i den månaden.", "Stockholm")
    need(b2, "Dag före helgdag och under juli månad ska dock ingen skatt tas ut.", "Göteborg")
    need(b2, "inom 60 minuter från en passage", "Göteborg")
    for name in sorted(BACKA):
        need(b2, name, "Göteborg point 5")
    m = re.search(r"2018:200\s+1\. Denna lag träder i kraft den (\d+) (\w+) (\d{4})", t)
    date = f"{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"

    stations = {"stockholm": [], "goteborg": []}
    for line in open(os.path.join(fetched, "se-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("highway") != "toll_gantry" or p.get("operator") != "Transportstyrelsen" or not p.get("name") or g["type"] != "Point":
            continue
        web = p.get("website", "")
        city = "stockholm" if "stockholm" in web else "goteborg" if "goteborg" in web else None
        if city is None:
            lon, lat = g["coordinates"]
            city = "stockholm" if 59.0 < lat < 59.6 else "goteborg" if 57.5 < lat < 58.0 else None
        if city == "goteborg" and p["name"] in BACKA:
            continue
        if city:
            lon, lat = g["coordinates"]
            stations[city].append({"name": p["name"], "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0,
                                   "schedule": "essingeleden" if p["name"] == "Essingeleden" else "inner" if city == "stockholm" else "goteborg"})
    for c, s in stations.items():
        s.sort(key=lambda x: (x["name"], x["lat"], x["lon"]))
        print(f"{c}: {len(s)} gantries, {len({x['name'] for x in s})} stations")
        if len(s) < 20:
            sys.exit(f"{c}: too few gantries in OpenStreetMap")
    law = "Lag (2004:629) om trängselskatt"
    src = [{"title": "Lag (2004:629) om trängselskatt, consolidated (Riksdagen)", "url": "https://data.riksdagen.se/dokument/sfs-2004-629.html"}]
    tables = {
        "stockholm": {
            "name": "Stockholm congestion tax (trängselskatt)",
            "law": law + ", bilaga 1: per passage of a charging station, by time of day, inner city or Essingeleden, low or high season; at most " + f"{cap} SEK a day ({cap_high} in high season); weekdays, not the day before a public holiday (except before Good Friday, Ascension, All Saints, and 1 May and National Day on weekdays), in July only its first five weekdays. Foreign-registered vehicles pay too (4 §). Stations: Transportstyrelsen's gantries in OpenStreetMap.",
            "sources": src + [{"title": "Transportstyrelsen: Trängselskatt i Stockholm", "url": "https://www.transportstyrelsen.se/sv/vagtrafik/fordon/skatter-och-avgifter/trangselskatt/trangselskatt-i-stockholm/"}],
            "congestion": {"schedules": {"inner": inner, "essingeleden": essinge},
                           "high_season": [["03-01", "midsummer_eve-1"], ["08-15", "11-30"]],
                           "day_cap": cap, "day_cap_high": cap_high, "july": "first5",
                           "eve_taxed": ["good_friday", "ascension", "all_saints", "may_1", "june_6"]}},
        "goteborg": {
            "name": "Göteborg congestion tax (trängselskatt)",
            "law": law + f", bilaga 2: per passage of a charging station, by time of day; passages within 60 minutes pay once; at most {cap_gbg} SEK a day; weekdays, not the day before a public holiday nor in July. Foreign-registered vehicles pay too (4 §). Stations: Transportstyrelsen's gantries in OpenStreetMap; the Backa stations (taxed only with a control point within 30 minutes) are left out.",
            "sources": src + [{"title": "Transportstyrelsen: Trängselskatt i Göteborg", "url": "https://www.transportstyrelsen.se/sv/vagtrafik/fordon/skatter-och-avgifter/trangselskatt/trangselskatt-i-goteborg/"}],
            "congestion": {"schedules": {"goteborg": gbg}, "day_cap": cap_gbg, "multi_pass_minutes": 60, "july": "free"}},
    }
    os.makedirs(out, exist_ok=True)
    for c, tb in tables.items():
        tb = {"country": "SE", "currency": "SEK", "valid_from": date, **tb,
              "vehicles": "All vehicles, Swedish and foreign", "tolled_roads": f"The charging stations of {c.capitalize().replace('Goteborg', 'Göteborg')}.",
              "crossings": True, "point_match_km": 0.03, "toll_points": stations[c], "rows": []}
        path = os.path.join(out, f"se-congestion-{c}-{date}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
