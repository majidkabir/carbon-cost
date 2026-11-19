"""Builds the A4 Katowice-Kraków concession toll (pl-a4-<date>.json) from
Stalexport Autostrada Małopolska's price list (pl-a4-tolls.html, the Polish page; for the
list of 3 April 2023, of which no copy of the page is kept, the operator's
press release, pl-a4-news.html): the toll
by vehicle category, collected at each of its two toll plazas, Mysłowice
(PPO Brzęczkowice) and Balice, in both directions. The plazas are placed at
their named toll booths in OpenStreetMap (pl-concessions-osm.json).

The categories go by the motor vehicle's axles and whether it tows a
trailer: 2 axles, or 2 axles with trailers; 3 axles, or 2 axles (twin
wheels) with trailers; more than 3 axles, or 3 axles with trailers. The
table counts the motor vehicle's axles (motor_axles) and its classes say
whether there is a trailer.

Usage: python3 pl_a4.py <fetched dir> <out dir>
"""
import html
import json
import math
import os
import re
import sys

MONTHS = {m: i + 1 for i, m in enumerate(("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
                                          "września", "października", "listopada", "grudnia"))}
URL = "https://www.autostrada-a4.com.pl/pl/oplaty/oplaty-i-sposoby-wnoszenia-oplat-cennik"
PLAZAS = (("Mysłowice", r"^PPO ?Brzęczkowice$"), ("Balice", r"^PPO ?Balice$"))
# The press release of the tolls from 3 April 2023 (the page then held no copy of the list).
NEWS = "https://autostrada-a4.com.pl/en/about-us/komunikaty-prasowe/New-toll-rates-on-the-A4-Katowice-Krakow-motorway-do-not-apply-to-everyone--you-may-still-be-allowed-to-pay-the-previous-rate-at-the-toll-plaza/idn:2551"
EN = {m: i + 1 for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                                      "November", "December"))}


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def main(fetched, out):
    try:
        d = json.load(open(os.path.join(fetched, "pl-concessions-osm.json")))
    except (OSError, ValueError):
        print("A4 Katowice-Kraków: OpenStreetMap not fetched; not built")
        return
    # Before 2024 no copy of the price list page holds the list: the
    # operator's press release of the change gives every category's toll.
    news = os.path.join(fetched, "pl-a4-news.html")
    if not os.path.exists(os.path.join(fetched, "pl-a4-tolls.html")) and os.path.exists(news):
        return from_news(d, news, out)
    # The text read in Chrome stands in only in the tables workflow's
    # fetched/ (it has fetch.py's manifest.json), never for an archived copy.
    p = os.path.join(fetched, "pl-a4-tolls.html")
    workflow = os.path.exists(os.path.join(fetched, "manifest.json"))
    if not os.path.exists(p) and not workflow:
        print("A4 Katowice-Kraków: price list not fetched; not built")
        return
    t = text(p) if os.path.exists(p) else ""
    how = "fetched"
    if not re.search(r"za przejazd autostradą A4 Katowice-Kraków,? (?:które obowiązują|obowiązujące) od", t):
        # The workflow's copy isn't the price list (a bot check): the text read in Chrome.
        cap = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser", "pl-a4-cennik.txt")
        t = re.sub(r"\s+", " ", "\n".join(l for l in open(cap, encoding="utf-8") if not l.startswith("#")))
        how = "browser"
        print("A4 Katowice-Kraków: read from", cap)
    # The page's wording as it has been since 2023 (a comma here and there, "które obowiązują").
    m = re.search(r"Opłaty\* za przejazd autostradą A4 Katowice-Kraków,? (?:które obowiązują|obowiązujące) od (\d+) (\w+) (\d{4}) r\. .{0,200}?"
                  r"2 pojazdy samochodowe o dwóch osiach, z których co najmniej jedna wyposażona jest w koło bliźniacze,? i pojazdy samochodowe o dwóch osiach z przyczepami (\d+) zł "
                  r"3 pojazdy samochodowe o trzech osiach i pojazdy samochodowe o dwóch osiach, z których co najmniej jedna wyposażona jest w koło bliźniacze z przyczepami (\d+) zł "
                  r"4 pojazdy samochodowe o więcej niż trzech osiach, pojazdy samochodowe o trzech osiach z przyczepami, i pojazdy samochodowe o więcej niż trzech osiach z przyczepami (\d+) zł "
                  r".{0,300}?Powyższe opłaty pobierane są na każdym Placu Poboru Opłat, tj\. w Mysłowicach oraz w Balicach", t)
    inv = ("bilet jednorazowy wystawiany przez inkasenta na Placu Poboru Opłat jest fakturą" in t
           or "fakturą dokumentującą przejazd autostradą płatną jest bilet jednorazowy" in t)
    if not m or m.group(2) not in MONTHS:
        sys.exit("A4 Katowice-Kraków: price list not read")
    start = f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    c2, c3, c4 = (int(x) for x in m.groups()[3:6])
    source = {"title": "Stalexport Autostrada Małopolska: Opłaty i sposoby wnoszenia opłat (cennik)" + (" (read in Chrome: tools/tables/browser/pl-a4-cennik.txt)" if how == "browser" else ""), "url": URL}
    build(d, start, c2, c3, c4, inv, source, out)


def from_news(d, path, out):
    """The tolls from Stalexport's press release of a change ("Starting from
    3 April this year ... PLN 27 for categories 2 and 3 ... PLN 46 for
    categories 4 and 5"), dated by the release (30 03 2023)."""
    raw = open(path, encoding="utf-8", errors="replace").read()
    t = text(path)
    day = re.search(r"\b(\d\d) (\d\d) (\d{4}) #Press", t)
    m = re.search(r"Starting from (\d{1,2}) (" + "|".join(EN) + r") this year, all vehicle categories .{0,200}?"
                  r"PLN (\d+) for category 1\b.{0,60}?PLN (\d+) for categories 2 and 3\b.{0,80}?PLN (\d+) for categories 4 and 5\b", t)
    if not (day and m):
        sys.exit("A4 Katowice-Kraków: the press release's date or tolls not read")
    start = f"{day.group(3)}-{EN[m.group(2)]:02d}-{int(m.group(1)):02d}"
    c3, c4 = int(m.group(4)), int(m.group(5))
    link = re.search(r'<link rel="canonical" href="([^"]+)"', raw)
    source = {"title": f"Stalexport Autostrada Małopolska: press release of {day.group(1)}.{day.group(2)}.{day.group(3)}, the tolls from {start} at each toll plaza",
              "url": link.group(1) if link else NEWS}
    build(d, start, c3, c3, c4, False, source, out)


def build(d, start, c2, c3, c4, inv, source, out):
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    points = []
    for name, pat in PLAZAS:
        booths = [e for e in d["elements"] if e.get("type") == "node" and re.search(pat, e.get("tags", {}).get("name", ""))]
        if not booths:
            sys.exit(f"A4 Katowice-Kraków: no toll booths of {name} in OpenStreetMap")
        lat = sum(b["lat"] for b in booths) / len(booths)
        lon = sum(b["lon"] for b in booths) / len(booths)
        if max(math.hypot((b["lat"] - lat) * 111.2, (b["lon"] - lon) * 111.2 * math.cos(math.radians(lat))) for b in booths) > 0.5:
            sys.exit(f"A4 Katowice-Kraków: {name}'s booths are more than 500 m apart")
        points.append({"name": f"A4 {name} toll plaza", "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0,
                       "classes": [{"min_axles": 4, "rate": c4},
                                   {"min_axles": 3, "max_axles": 3, "trailer": True, "rate": c4},
                                   {"min_axles": 3, "max_axles": 3, "trailer": False, "rate": c3},
                                   {"max_axles": 2, "trailer": True, "rate": c3},
                                   {"max_axles": 2, "trailer": False, "rate": c2}]})
    tb = {"country": "PL", "currency": "PLN", "valid_from": start, "crossings": True, "motor_axles": True, "osm_extract": stamp,
          "name": "A4 Katowice-Kraków (Stalexport Autostrada Małopolska)",
          "law": (f"Stalexport Autostrada Małopolska's tolls (cennik) from {start}, collected at each of the two toll plazas (Mysłowice and Balice), either way, as the price paid at the plaza"
                  + (" (VAT included: the plaza's ticket is the VAT invoice, rozporządzenie Ministra Finansów of 29 October 2021, Dz.U. 2021 poz. 1979, § 3)" if inv else "") + ": "
                  f"category 2 (two axles with twin wheels, or two axles with trailers) PLN {c2}, category 3 (three axles, or two axles with twin wheels with trailers) PLN {c3}, "
                  f"category 4 (more than three axles, or three axles with trailers) PLN {c4}. A semi-trailer counts as a trailer (Prawo o ruchu drogowym art. 2 pkt 44). "
                  "The category goes by the motor vehicle's own axles (give truck.motor_axles; without it all the truck's axles count) and whether it tows a trailer. "
                  "The e-TOLL doesn't charge this stretch. The plazas are placed at their named toll booths in OpenStreetMap. Discounts for automatic payment (A4Go, videotolling) aren't modelled."),
          "sources": [source,
                      {"title": "OpenStreetMap (Overpass API): toll booths of the Mysłowice (Brzęczkowice) and Balice plazas", "url": "https://www.openstreetmap.org/"}],
          "vehicles": "Vehicles over 3.5 t", "min_kg": 3501,
          "tolled_roads": "A4 Katowice (Murckowska) - Kraków (Balice), km 340.2-401.1: toll plazas at Mysłowice (Brzęczkowice) and Balice.",
          "point_match_km": 0.3, "toll_points": points, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"pl-a4-{start}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, c2, c3, c4)


if __name__ == "__main__":
    main(*sys.argv[1:])
