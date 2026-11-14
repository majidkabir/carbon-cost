"""Builds the tables of tunnels and bridges charged per passage on top of
the countries' own tolls (each a "crossings" table, priced wherever a
route passes it): the Herrentunnel and the Warnowtunnel (DE), the Westerscheldetunnel (NL), the Liefkenshoektunnel (BE),
the Great St Bernard tunnel (CH and IT), the Dartford Crossing, the
Tyne Tunnels and the Blackwall and Silvertown tunnels (GB).

Usage: python3 tunnels.py transcribed/ fetched/ out-dir -> out-dir/<cc>-<crossing>-<date>.json

The Herrentunnel's prices are published only as an image, transcribed
by hand into transcribed/de-herrentunnel-2025.json (check_transcribed.py
says when the image changes).

Prices come from each operator's or government's page (fetch.py's
nl-westerscheldetunnel.html, ch-gsb.html, gb-dartford.html) and, for
Dartford, the charging scheme orders on legislation.gov.uk
(gb-dartford-2013.html, gb-dartford-2025.html). Where each charge is
taken comes from OpenStreetMap (tunnels-osm.json, an Overpass query):

- Westerscheldetunnel: the toll plaza's booths (operator N.V.
  Westerscheldetunnel), either direction.
- Great St Bernard: the Swiss plaza (the booth at the tunnel's north
  end, Bourg-Saint-Pierre) charges southbound in CHF, the Italian plaza
  (the booth named Traforo del Gran San Bernardo, Saint-Rhémy) northbound
  in EUR; each heading is along the tunnel's OSM way.
- Herrentunnel: the plaza's booths named Herrentunnel (operator
  Herrentunnel Lübeck GmbH & Co. KG), either direction.
- Liefkenshoektunnel: the plaza's booths (operator NV Tunnel
  Liefkenshoek), either direction; prices read in Chrome
  (browser/be-liefkenshoek.txt).
- Warnowtunnel: the plaza's booths (operator Warnowtunnel), either
  direction; prices from the state ordinance, read in Chrome
  (browser/de-warnow-mauthvo.txt).
- Tyne Tunnels: free-flow: the middle of each one-way A19 bore's longest
  way (tunnels-osm-tyne.json), in its direction.
- Dartford: free-flow, no booths: the middle of the northbound tunnels
  (A282, tunnel=yes) and of the southbound bridge (A282, bridge=yes),
  each in its direction.
"""
import html, json, math, os, re, sys


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def num(s):
    return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)


def bearing(a, b):
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = math.cos(math.radians(a[0])) * math.sin(math.radians(b[0])) - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1]))
    return round(math.degrees(math.atan2(y, x)) % 360, 1)


def km(a, b):
    return math.hypot((a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 111.2)


def middle(way):
    """The point halfway along a way, and the heading of its geometry there."""
    g = [(p["lat"], p["lon"]) for p in way["geometry"]]
    total = sum(km(g[i], g[i + 1]) for i in range(len(g) - 1))
    run = 0
    for i in range(len(g) - 1):
        d = km(g[i], g[i + 1])
        if run + d >= total / 2:
            f = (total / 2 - run) / d if d else 0
            p = (g[i][0] + f * (g[i + 1][0] - g[i][0]), g[i][1] + f * (g[i + 1][1] - g[i][1]))
            return round(p[0], 6), round(p[1], 6), bearing(g[i], g[i + 1])
        run += d
    raise ValueError("empty way")


def centre(nodes):
    lat = sum(n["lat"] for n in nodes) / len(nodes)
    lon = sum(n["lon"] for n in nodes) / len(nodes)
    if max(km((lat, lon), (n["lat"], n["lon"])) for n in nodes) > 0.3:
        sys.exit(f"booths more than 300 m apart: {[n['id'] for n in nodes]}")
    return round(lat, 6), round(lon, 6)


def write(out, t, name):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}-{t['valid_from']}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


def westerschelde(fetched, out, osm, stamp):
    p = os.path.join(fetched, "nl-westerscheldetunnel.html")
    if not os.path.exists(p):
        print("Westerscheldetunnel: page not fetched; not built")
        return
    t = text(p)
    cats = {}
    for c in (3, 4):
        m = re.search(rf"cat\. {c} (.*?) € ([\d,]+) Standaard € ([\d,]+) T-Tag", t)
        if not m:
            sys.exit(f"Westerscheldetunnel: category {c} not found")
        cats[c] = (m.group(1).strip(), num(m.group(2)), num(m.group(3)))
    assert "Lengte < 12 meter en hoogte > 3 meter" in cats[3][0] and "Lengte > 12 meter en hoogte > 3 meter" in cats[4][0], cats
    booths = [e for e in osm if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"
              and e["tags"].get("operator") == "N.V. Westerscheldetunnel"]
    if not booths:
        sys.exit("Westerscheldetunnel: no toll booths in OpenStreetMap")
    lat, lon = centre(booths)
    write(out, {
        "country": "NL", "currency": "EUR", "valid_from": "2026-01-01", "crossings": True, "osm_extract": stamp,
        "name": "Westerscheldetunnel toll",
        "law": "Tunnelwet Westerschelde: N.V. Westerscheldetunnel's tariffs per passage, by the whole vehicle's length and height: category 3 (under 12 m, over 3 m high) and 4 (over 12 m), the standard price, with `etc` the T-Tag price. Trucks over 3.5 t are taken to be over 3 m high. Cars and vans pay nothing since 30 December 2024; trucks still pay. The page names no date: the prices are those it published when fetched.",
        "sources": [{"title": "N.V. Westerscheldetunnel: tarieven", "url": "https://www.westerscheldetunnel.nl/nl/tarieven-betaalmiddelen/tarieven/"}],
        "vehicles": "Vehicles over 3 m high (here: trucks over 3.5 t), by length", "min_kg": 3501,
        "tolled_roads": "The Westerscheldetunnel (N62 Terneuzen-Ellewoutsdijk), charged at its toll plaza either way.",
        "point_match_km": 0.15,
        "toll_points": [{"name": "Westerscheldetunnel", "lat": lat, "lon": lon, "rate": 0, "classes": [
            {"min_kg": 3501, "max_length_m": 12, "rate": cats[3][1], "etc_rate": cats[3][2]},
            {"min_kg": 3501, "min_length_m": 12, "rate": cats[4][1], "etc_rate": cats[4][2]}]}],
        "rows": [],
    }, "nl-westerscheldetunnel")


def gsb(fetched, out, osm, stamp):
    p = os.path.join(fetched, "ch-gsb.html")
    if not os.path.exists(p):
        print("Great St Bernard: page not fetched; not built")
        return
    t = text(p)
    m = re.search(r"Tariffe DAL (\d\d)\.(\d\d)\.(\d{4})", t)
    since = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    prices = {}
    for key, label in (("2", r"Classe B2/B3 Camion a due assi"), ("3", r"Classe 3A/3B Camion a tre assi"), ("4", r"Classe 4 Veicoli a quattro o più assi")):
        m = re.search(label + r".*?SOLO ANDATA ([\d.,]+) EUR ([\d.,]+) CHF", t)
        if not m:
            sys.exit(f"Great St Bernard: class {key} not found")
        prices[key] = (num(m.group(1)), num(m.group(2)))
    ways = {e["tags"]["name"]: e for e in osm if e["type"] == "way" and e.get("tags", {}).get("name") in ("Tunnel du Grand-Saint-Bernard", "Traforo del Gran San Bernardo")}
    if len(ways) != 2:
        sys.exit(f"Great St Bernard: tunnel ways {list(ways)}")
    # The Swiss way runs from the border north to the Swiss portal; the
    # Italian way from the Italian portal north to the border.
    ch, it = ways["Tunnel du Grand-Saint-Bernard"]["geometry"], ways["Traforo del Gran San Bernardo"]["geometry"]
    north, south = (ch[-1]["lat"], ch[-1]["lon"]), (it[0]["lat"], it[0]["lon"])
    if north[0] < south[0]:
        sys.exit("Great St Bernard: unexpected way directions")
    southbound, northbound = bearing(north, south), bearing(south, north)
    booths = [e for e in osm if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth" and 45.80 < e["lat"] < 45.92 and 7.10 < e["lon"] < 7.25]
    chb = [b for b in booths if km((b["lat"], b["lon"]), north) < 0.5]
    itb = [b for b in booths if km((b["lat"], b["lon"]), south) < 0.5]
    if not chb or not itb:
        sys.exit(f"Great St Bernard: plazas not found ({len(chb)} Swiss, {len(itb)} Italian booths)")
    law = (f"Tunnel du Grand-Saint-Bernard (SISEX SA, Swiss side; SITRASB S.p.A., Italian side): one-way tariff from {since}, "
           "paid at the plaza where the trip enters, in CHF on the Swiss side and EUR on the Italian side: trucks over 3 m high with 2 axles (class B2), "
           "3 axles (3A) or 4 or more (4). Trucks over 3.5 t are taken to be over 3 m high.")
    src = [{"title": "Tunnel du Grand-Saint-Bernard: tariffs", "url": "https://www.letunnel.com/"}]
    for cc, cur, i, (lat, lon), head, plaza in (("CH", "CHF", 1, centre(chb), southbound, "Bourg-Saint-Pierre (southbound)"),
                                                ("IT", "EUR", 0, centre(itb), northbound, "Saint-Rhémy (northbound)")):
        write(out, {
            "country": cc, "currency": cur, "valid_from": since, "crossings": True, "osm_extract": stamp,
            "name": "Great St Bernard tunnel toll, " + plaza,
            "law": law, "sources": src,
            "vehicles": "Trucks over 3 m high (here: over 3.5 t), by axles", "min_kg": 3501,
            "tolled_roads": f"The Great St Bernard tunnel, charged at the {plaza} plaza.",
            "point_match_km": 0.2,
            "toll_points": [{"name": "Great St Bernard tunnel", "lat": lat, "lon": lon, "heading": head, "rate": 0, "classes": [
                {"min_kg": 3501, "max_axles": 2, "rate": prices["2"][i]},
                {"min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": prices["3"][i]},
                {"min_kg": 3501, "min_axles": 4, "rate": prices["4"][i]}]}],
            "rows": [],
        }, f"{cc.lower()}-great-st-bernard")


def herrentunnel(transcribed, out, osm, stamp):
    tr = json.load(open(os.path.join(transcribed, "de-herrentunnel-2025.json"), encoding="utf-8"))
    booths = [e for e in osm if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth"
              and e["tags"].get("operator") == "Herrentunnel Lübeck GmbH & Co. KG" and e["tags"].get("name", "").startswith("Herrentunnel")]
    if not booths:
        sys.exit("Herrentunnel: no toll booths in OpenStreetMap")
    lat, lon = centre(booths)
    c = {x["class"]: x for x in tr["classes"]}
    write(out, {
        "country": "DE", "currency": "EUR", "valid_from": tr["valid_from"], "crossings": True, "osm_extract": stamp,
        "name": "Herrentunnel toll (Lübeck)",
        "law": "Fernstraßenbauprivatfinanzierungsgesetz: the toll of the Herrentunnel Lübeck GmbH & Co. KG, as its Gebührentabelle (valid from 1 March 2025) gives it per passage, by height over the front axle (over 130 cm) and axles: class B (2 axles), C (3), D (4 or more); the cash price, with `etc` the Quick-Box/RFID price. Trucks over 3.5 t are taken to be over 130 cm.",
        "sources": [{"title": "Herrentunnel: Gebührentabelle (gültig ab 01.03.2025)", "url": tr["source"]["page"]},
                    {"title": "Herrentunnel: the toll table image, as transcribed in tools/tables/transcribed/de-herrentunnel-2025.json", "url": tr["source"]["url"]}],
        "vehicles": "Vehicles over 130 cm high at the front axle (here: trucks over 3.5 t), by axles", "min_kg": 3501,
        "tolled_roads": "The Herrentunnel (B 104/B 75 Lübeck-Travemünde), charged at its toll plaza either way.",
        "point_match_km": 0.15,
        "toll_points": [{"name": "Herrentunnel", "lat": lat, "lon": lon, "rate": 0, "classes": [
            {"min_kg": 3501, "max_axles": 2, "rate": c["B"]["cash"], "etc_rate": c["B"]["tag"]},
            {"min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": c["C"]["cash"], "etc_rate": c["C"]["tag"]},
            {"min_kg": 3501, "min_axles": 4, "rate": c["D"]["cash"], "etc_rate": c["D"]["tag"]}]}],
        "rows": [],
    }, "de-herrentunnel")


def warnow(browser, out, osm, stamp):
    """The Warnowtunnel (Rostock): the toll of the Warnow-QuerungMautHVO
    M-V's Anlage, read in Chrome (browser/de-warnow-mauthvo.txt): winter
    (1 Nov - 30 Apr) and summer (1 May - 31 Oct) prices per passage, the
    "360 Tage" price as `etc`; at the plaza's booths (operator
    Warnowtunnel), either direction."""
    try:
        t = open(os.path.join(browser, "de-warnow-mauthvo.txt"), encoding="utf-8").read()
    except OSError:
        print("Warnowtunnel: browser/de-warnow-mauthvo.txt missing; not built")
        return
    since = re.search(r"^Anlage (\d\d)\.(\d\d)\.(\d{4})$", t, re.M)
    amend = re.search(r"Anlage neu gefasst durch Verordnung vom ([^(]+?) \((GVOBl\. M-V S\. \d+)\)", t)
    head = "Kategorie | Höhe | Achsen | Fahrzeugtyp (Beispiele) | 360 Tage | Winter 1. Nov. - 30. April | Sommer 1. Mai - 31. Okt."
    rows = {m.group(1): [num(x) for x in m.group(3, 4, 5)] for m in re.finditer(r"^([345]) \| ≥ 2,60 m \| ([=≥] \d) \| [^|]+\| ([\d,]+) EUR \| ([\d,]+) EUR \| ([\d,]+) EUR$", t, re.M)}
    if not since or not amend or head not in t or len(rows) != 3 or "= 2 | Lkw 12 t" not in t or "= 3 | Lkw 20 t" not in t or "≥ 4 | Lkw 40 t" not in t:
        sys.exit("Warnowtunnel: the captured ordinance changed")
    booths = [e for e in osm if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth" and e["tags"].get("operator") == "Warnowtunnel"]
    if not booths:
        sys.exit("Warnowtunnel: no toll booths in OpenStreetMap")
    lat, lon = centre(booths)
    vf = f"{since.group(3)}-{since.group(2)}-{since.group(1)}"
    cls = []
    for k, lo, hi in (("3", 0, 2), ("4", 3, 3), ("5", 4, 0)):
        tag, winter, summer = rows[k]
        c = {"min_kg": 3501, "rate": winter, "etc_rate": tag, "high_rate": summer}
        if lo:
            c["min_axles"] = lo
        if hi:
            c["max_axles"] = hi
        cls.append(c)
    write(out, {
        "country": "DE", "currency": "EUR", "valid_from": vf, "crossings": True, "osm_extract": stamp,
        "name": "Warnowtunnel toll (Rostock)",
        "law": (f"Warnow-QuerungMautHVO M-V (Anlage as newly set by the Verordnung of {amend.group(1)}, {amend.group(2)}, valid from {since.group(1)}.{since.group(2)}.{since.group(3)}): "
                "the toll per passage of the Warnow-Querung (B 105, Rostock), VAT included, for vehicles 2.60 m high or more by axles: category 3 (2 axles), 4 (3), 5 (4 or more); "
                "the winter price (1 November - 30 April), the summer price (1 May - 31 October) as the high season, and the '360 Tage' price as `etc`. Trucks over 3.5 t are taken to be 2.60 m high or more."),
        "sources": [{"title": "Landesrecht Mecklenburg-Vorpommern: Warnow-QuerungMautHVO M-V, Gesamtausgabe (read in Chrome: tools/tables/browser/de-warnow-mauthvo.txt)", "url": "https://www.landesrecht-mv.de/bsmv/document/jlr-NNLMV0000717F"}],
        "vehicles": "Vehicles 2.60 m high or more (here: trucks over 3.5 t), by axles", "min_kg": 3501,
        "tolled_roads": "The Warnowtunnel (B 105 Rostock, km 1+040 to 3+160), charged at its toll plaza either way.",
        "point_match_km": 0.15,
        "toll_points": [{"name": "Warnowtunnel", "lat": lat, "lon": lon, "rate": 0, "classes": cls, "high_season": {"months": [5, 6, 7, 8, 9, 10]}}],
        "rows": [],
    }, "de-warnowtunnel")


def liefkenshoek(browser, out, osm, stamp):
    """The Liefkenshoektunnel (Antwerp): category 2 (3 m high or more) per
    passage either way, a calendar year's tariff from 1 January; the cash
    (standaardtarief) price, `etc` the Teletolbadge & OBU price; cheaper
    22:00-06:00. Read in Chrome (browser/be-liefkenshoek.txt); at the
    plaza's booths (operator NV Tunnel Liefkenshoek)."""
    try:
        t = open(os.path.join(browser, "be-liefkenshoek.txt"), encoding="utf-8").read()
    except OSError:
        print("Liefkenshoektunnel: browser/be-liefkenshoek.txt missing; not built")
        return
    head = "Categorie 1 (24/7) Categorie 2 (22u00-06u00) Categorie 2 (06u01-21u59)"
    eur = r"€ ([\d,]+)"
    years = {}
    for m in re.finditer(r"^Tarieven (\d{4})\n" + re.escape(head) + r"\nTeletolbadge & OBU " + " ".join([eur] * 3) + r"\nBank-Tank-Creditkaart " + " ".join([eur] * 3) + r"\nCash \(standaardtarief\) " + " ".join([eur] * 3) + "$", t, re.M):
        years[m.group(1)] = [num(x) for x in m.groups()[1:]]
    cat = "Voertuigen met een totale hoogte van 3 meter of meer vallen onder categorie 2" in t and "Andere criteria (aantal assen, gebruik, lengte, gewicht" in t
    if not years or not cat or t.count("Tarieven 2") != len(years):
        sys.exit(f"Liefkenshoektunnel: the captured pages changed ({sorted(years)}, {cat})")
    booths = [e for e in osm if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth" and e["tags"].get("operator") == "NV Tunnel Liefkenshoek"]
    if not booths:
        sys.exit("Liefkenshoektunnel: no toll booths in OpenStreetMap")
    lat, lon = centre(booths)
    ys = sorted(years)
    for i, y in enumerate(ys):
        obu_n, obu_d, card_n, card_d, cash_n, cash_d = (years[y][k] for k in (1, 2, 4, 5, 7, 8))
        tb = {
            "country": "BE", "currency": "EUR", "valid_from": f"{y}-01-01", "crossings": True, "osm_extract": stamp,
            "name": "Liefkenshoektunnel toll (Antwerp)",
            "law": (f"NV Tunnel Liefkenshoek's tariffs {y}: category 2 (vehicles 3 m high or more; trucks over 3.5 t are taken to be) per passage either way, VAT included: "
                    f"EUR {cash_d:.2f} cash (standaardtarief) 06:01-21:59 and {cash_n:.2f} 22:00-06:00; `etc` the Teletolbadge & OBU price, {obu_d:.2f} and {obu_n:.2f} "
                    f"(bank, fuel or credit card: {card_d:.2f} and {card_n:.2f}, not modelled). Without a departure time, the day price."),
            "sources": [{"title": "NV Tunnel Liefkenshoek: Tarieven & abonnement, and Veelgestelde vragen (categories) (read in Chrome: tools/tables/browser/be-liefkenshoek.txt)", "url": "https://www.liefkenshoektunnel.be/nl/tarieven-abonnementen"}],
            "vehicles": "Category 2: vehicles 3 m high or more (here: trucks over 3.5 t)", "min_kg": 3501,
            "tolled_roads": "The Liefkenshoektunnel (R2, Antwerp), charged at its toll plaza either way.",
            "point_match_km": 0.15,
            "toll_points": [{"name": "Liefkenshoektunnel", "lat": lat, "lon": lon, "rate": 0, "night_hours": ["22:00", "06:00"],
                             "classes": [{"min_kg": 3501, "rate": cash_d, "etc_rate": obu_d, "night_rate": cash_n, "night_etc_rate": obu_n}]}],
            "rows": [],
        }
        if i + 1 < len(ys):
            tb["valid_to"] = f"{y}-12-31"
        write(out, tb, "be-liefkenshoek")


def dartford(fetched, out, osm, stamp):
    paths = [os.path.join(fetched, f) for f in ("gb-dartford.html", "gb-dartford-2013.html", "gb-dartford-2025.html")]
    if not all(os.path.exists(p) for p in paths):
        print("Dartford: a page wasn't fetched; not built")
        return
    gov, o13, o25 = (text(p) for p in paths)
    # The 2013 Order, Schedule 2: column 3 (first, barrier regime) and
    # column 4 (second, free-flow regime, in force since 30 November 2014).
    old = {}
    for item in ("C", "D"):
        m = re.search(rf" {item} Classes— .*? £([\d.]+) £([\d.]+) (?:[A-E] Classes|Article|Column|$)", o13)
        if not m:
            sys.exit(f"Dartford 2013 Order: item {item} not found")
        old[item] = float(m.group(2))
    new = {}
    for item in ("C", "D"):
        m = re.search(rf"at item {item}, for “£([\d.]+)” substitute “£([\d.]+)”", o25)
        if not m or float(m.group(1)) != old[item]:
            sys.exit(f"Dartford 2025 Order: item {item} not found or not varying {old[item]}")
        new[item] = float(m.group(2))
    since = re.search(r"comes into force on (\d+)(?:st|nd|rd|th) (\w+) (\d{4})", o25)
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    since = f"{since.group(3)}-{months.index(since.group(2)) + 1:02d}-{int(since.group(1)):02d}"
    # GOV.UK: one-off, pay as you go and pre-pay (account) prices, and the
    # hours the charge applies.
    pre = {}
    for item, label in (("C", "Vehicles with 2 axles"), ("D", "Vehicles with more than 2 axles")):
        m = re.search(re.escape(label) + rf" {item} £([\d.]+) £([\d.]+) £([\d.]+)", gov)
        if not m or float(m.group(1)) != new[item]:
            sys.exit(f"Dartford GOV.UK: class {item} not found or not the Order's {new[item]}")
        pre[item] = float(m.group(3))
    if "between 6am and 10pm" not in gov:
        sys.exit("Dartford GOV.UK: charging hours changed")
    pts = []
    for e in osm:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("ref") == "A282" and (t.get("tunnel") == "yes" or t.get("bridge") == "yes") and t.get("oneway") == "yes" and len(e["geometry"]) > 1:
            g = e["geometry"]
            if km((g[0]["lat"], g[0]["lon"]), (g[-1]["lat"], g[-1]["lon"])) > 1:  # the crossing, not a short bridge
                pts.append((t.get("tunnel") == "yes", middle(e)))
    if sorted(p[0] for p in pts) != [False, True, True]:
        sys.exit(f"Dartford: expected one bridge and two tunnels in OpenStreetMap, got {pts}")
    law = ("The A282 Trunk Road (Dartford-Thurrock Crossing Charging Scheme) Order 2013 (S.I. 2013/2249), Schedule 2 column 4 (free-flow charging): "
           "class C (goods vehicles with two axles) and D (more than two axles), per crossing either way, from 6am to 10pm (GOV.UK)")
    src13 = {"title": "S.I. 2013/2249, the A282 Trunk Road (Dartford-Thurrock Crossing Charging Scheme) Order 2013", "url": "https://www.legislation.gov.uk/uksi/2013/2249/made"}
    src25 = {"title": "S.I. 2025/853, the Variation Order 2025", "url": "https://www.legislation.gov.uk/uksi/2025/853/made"}
    gsrc = {"title": "GOV.UK: Dartford Crossing charges", "url": "https://www.gov.uk/pay-dartford-crossing-charge/charges"}
    for vf, vt, price, etc, extra, srcs in (("2024-01-01", prev_day(since), old, {}, ".", [src13, gsrc]),
                                             (since, "", new, pre, f", as varied from {since} by S.I. 2025/853; with `etc` the pre-pay account price GOV.UK gives.", [src13, src25, gsrc])):
        tps = []
        for tunnel, (lat, lon, head) in pts:
            cl = []
            for item, ax in (("C", {"max_axles": 2}), ("D", {"min_axles": 3})):
                c = {"min_kg": 3501, **ax, "rate": price[item]}
                if etc:
                    c["etc_rate"] = etc[item]
                cl.append(c)
            tps.append({"name": "Dartford Crossing", "lat": lat, "lon": lon, "heading": head, "rate": 0, "classes": cl, "free_hours": ["22:00", "05:59"]})
        t = {"country": "GB", "currency": "GBP", "valid_from": vf, "crossings": True, "osm_extract": stamp,
             "name": "Dartford Crossing charge (Dart Charge)", "law": law + extra, "sources": srcs,
             "vehicles": "Goods vehicles, by axles (here: over 3.5 t)", "min_kg": 3501,
             "tolled_roads": "The Dartford-Thurrock Crossing (A282): the northbound tunnels and the southbound Queen Elizabeth II Bridge.",
             "point_match_km": 0.15, "toll_points": tps, "rows": []}
        if vt:
            t["valid_to"] = vt
        write(out, t, "gb-dartford")


def tyne(fetched, out):
    """The Tyne Tunnels (A19): the tolls of each River Tyne (Tunnels)
    (Revision of Toll(s)) Order, class 3 (other than motorcycles and
    vehicles up to 3.5 t), with `etc` the permit holder's price."""
    try:
        d = json.load(open(os.path.join(fetched, "tunnels-osm-tyne.json")))
    except (OSError, ValueError):
        print("Tyne Tunnels: OpenStreetMap ways not fetched; not built")
        return
    # One point per bore (Tyne Tunnel, New Tyne Tunnel; each one-way): the
    # middle of its longest way, charged in that way's direction.
    bores = {}
    for e in d["elements"]:
        t = e.get("tags", {})
        g = e.get("geometry", [])
        if e["type"] == "way" and t.get("ref") == "A19" and t.get("tunnel") == "yes" and t.get("oneway") == "yes" and len(g) > 1:
            n = km((g[0]["lat"], g[0]["lon"]), (g[-1]["lat"], g[-1]["lon"]))
            if n > bores.get(t.get("name"), (0, None))[0]:
                bores[t.get("name")] = (n, e)
    if sorted(bores) != ["New Tyne Tunnel", "Tyne Tunnel"]:
        sys.exit(f"Tyne Tunnels: expected the two A19 bores, got {sorted(bores)}")
    pts = [middle(e) for _, e in bores.values()]
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    orders = []
    for y, si in ((2023, "2023/413"), (2024, "2024/479"), (2025, "2025/449")):
        o = text(os.path.join(fetched, f"gb-tyne-{y}.html"))
        since = re.search(r"come into force on (\d+)(?:st|nd|rd|th) (\w+) (\d{4})", o)
        m = re.search(r"Class 3 Mechanically propelled vehicle other than a vehicle in Classes 1 and 2 £([\d.]+) Class 3 permit holder after discount £([\d.]+)", o)
        if not since or not m or "maximum weight not exceeding 3.5 tonnes" not in o:
            sys.exit(f"Tyne Tunnels {y}: Order not as expected")
        months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        orders.append((f"{since.group(3)}-{months.index(since.group(2)) + 1:02d}-{int(since.group(1)):02d}", si, y, float(m.group(1)), float(m.group(2))))
    for i, (vf, si, y, rate, etc) in enumerate(orders):
        vt = prev_day(orders[i + 1][0]) if i + 1 < len(orders) else ""
        if vt and vt < "2024-01-01":
            continue
        t = {"country": "GB", "currency": "GBP", "valid_from": max(vf, "2024-01-01"), "crossings": True, "osm_extract": stamp,
             "name": "Tyne Tunnels toll",
             "law": f"Tyne and Wear Act 1976 s. 13 and the River Tyne (Tunnels) Order 2005: the River Tyne (Tunnels) (Revision of Toll{'s' if y == 2023 else ''}) Order {y} (S.I. {si}), in force from {vf}: class 3 (vehicles other than motorcycles and those up to 3.5 t) per passage either way; with `etc` the permit holder's price after discount.",
             "sources": [{"title": f"S.I. {si}, the River Tyne (Tunnels) Revision of Toll Order {y}", "url": f"https://www.legislation.gov.uk/uksi/{si}/made"}],
             "vehicles": "Vehicles over 3.5 t (class 3)", "min_kg": 3501,
             "tolled_roads": "The Tyne Tunnels (A19, Jarrow-Howdon), free-flow, either way.",
             "point_match_km": 0.15,
             "toll_points": [{"name": "Tyne Tunnels", "lat": lat, "lon": lon, "heading": head, "rate": 0, "classes": [{"min_kg": 3501, "rate": rate, "etc_rate": etc}]} for lat, lon, head in pts],
             "rows": []}
        if vt:
            t["valid_to"] = vt
        write(out, t, "gb-tyne-tunnels")


def thames(browser, fetched, out):
    """The Blackwall and Silvertown tunnels (TfL's user charge, from 7
    April 2025): per crossing either way, 06:00-22:00 except Christmas
    Day; heavy goods vehicles (N2, N3) pay the price charged online at
    all times, with `etc` the Auto Pay off-peak price. Charges from TfL's
    payment page and its press release of 23 July 2026, read in Chrome
    (browser/gb-tfl-tunnels.txt); one point per bore (OSM,
    tunnels-osm-thames.json): the middle of its longest one-way way."""
    t = re.sub(r"\s+", " ", " ".join(l for l in open(os.path.join(browser, "gb-tfl-tunnels.txt"), encoding="utf-8") if not l.startswith("# ")))
    cur = re.search(r"Tunnel charges increased on (\d+) (\w+) (\d{4})\. Current charges .*?Heavy goods vehicles £([\d.]+) £([\d.]+) £([\d.]+)", t)
    pr = re.search(r"press release PN-215, (\d+) (\w+) (\d{4}).*?opened on (\d+) (\w+) last year.*?Heavy Goods Vehicles £([\d.]+) will become £([\d.]+) £([\d.]+) will become £([\d.]+) £([\d.]+) will become £([\d.]+)", t)
    hours = "Charges apply from 06.00 - 22.00, 7 days a week in both directions." in t and "except Christmas Day" in t
    if not cur or not pr or not hours or "N2 | HGV" not in t or "N3 | HGV" not in t:
        sys.exit(f"Thames tunnels: the captured pages changed ({bool(cur)}, {bool(pr)}, {hours})")
    if (pr.group(7), pr.group(9), pr.group(11)) != (cur.group(4), cur.group(5), cur.group(6)):
        sys.exit("Thames tunnels: the press release's new charges aren't the page's current ones")
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    since = f"{cur.group(3)}-{months.index(cur.group(2)) + 1:02d}-{int(cur.group(1)):02d}"
    opened = f"{int(pr.group(3)) - 1}-{months.index(pr.group(5)) + 1:02d}-{int(pr.group(4)):02d}"
    try:
        d = json.load(open(os.path.join(fetched, "tunnels-osm-thames.json")))
    except (OSError, ValueError):
        print("Thames tunnels: OpenStreetMap ways not fetched; not built")
        return
    bores = {}
    for e in d["elements"]:
        tg, g = e.get("tags", {}), e.get("geometry", [])
        name = tg.get("name", "")
        if e["type"] != "way" or tg.get("oneway") != "yes" or len(g) < 2 or name not in ("Blackwall Tunnel", "Silvertown Tunnel"):
            continue
        n = km((g[0]["lat"], g[0]["lon"]), (g[-1]["lat"], g[-1]["lon"]))
        north = g[-1]["lat"] > g[0]["lat"]
        if n > bores.get((name, north), (0, None))[0]:
            bores[(name, north)] = (n, e)
    print("Thames tunnels in OSM:", {k: round(v[0], 2) for k, v in bores.items()})
    if len(bores) != 4:
        names = sorted(set((e.get("tags", {}).get("name"), e.get("tags", {}).get("ref"), e.get("tags", {}).get("oneway")) for e in d["elements"] if e["type"] == "way"))
        print("Thames tunnels: expected a northbound and a southbound bore of each tunnel; not built. Ways:", names)
        return
    pts = [middle(e) for _, e in bores.values()]
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    src = [{"title": "Transport for London: paying the Blackwall and Silvertown tunnels charge (read in Chrome, as TfL refuses the workflow)", "url": "https://tfl.gov.uk/modes/driving/silvertown-blackwall-tunnels-charge/paying-blackwall-and-silvertown-tunnel-charges"},
           {"title": "TfL press release PN-215 (23 July 2026): current and new user charges", "url": "https://tfl-newsroom.prgloo.com/news/new-report-shows-one-year-old-silvertown-tunnel-cuts-congestion-and-boosts-bus-use-alongside-improved-air-quality"}]
    for vf, vt, rate, etc in ((opened, prev_day(since), float(pr.group(8)), float(pr.group(6))), (since, "", float(cur.group(6)), float(cur.group(4)))):
        tb = {"country": "GB", "currency": "GBP", "valid_from": vf, "crossings": True, "osm_extract": stamp,
              "name": "Blackwall and Silvertown tunnels charge",
              "law": (f"The Silvertown Tunnel Order 2018 (user charges set by TfL): heavy goods vehicles (N2, N3) pay GBP {rate:.2f} per crossing either way, 06:00-22:00 every day except Christmas Day, paid online or by phone; "
                      f"with `etc` the Auto Pay off-peak price, GBP {etc:.2f} (Auto Pay's peak, weekdays 06:00-10:00 northbound and 16:00-19:00 southbound, is the full price, not modelled). "
                      + ("From the tunnel's opening; TfL's press release of 23 July 2026 gives these as the charges before 21 September 2026." if vt else f"From {since} (TfL).")),
              "sources": src, "vehicles": "Heavy goods vehicles (N2, N3: over 3.5 t)", "min_kg": 3501,
              "tolled_roads": "The Blackwall Tunnel (A102) and the Silvertown Tunnel under the Thames, each bore, either way.",
              "point_match_km": 0.15,
              "toll_points": [{"name": "Blackwall and Silvertown tunnels", "lat": lat, "lon": lon, "heading": head, "rate": 0,
                               "classes": [{"min_kg": 3501, "rate": rate, "etc_rate": etc}], "free_hours": ["22:00", "05:59"]} for lat, lon, head in pts],
              "rows": []}
        if vt:
            tb["valid_to"] = vt
        write(out, tb, "gb-thames-tunnels")


def longest(d, pattern):
    """The longest way of bridges-osm.json whose name matches."""
    ws = [e for e in d["elements"] if e["type"] == "way" and re.search(pattern, e.get("tags", {}).get("name", "")) and len(e.get("geometry", [])) > 1]
    return max(ws, key=lambda e: sum(km((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(e["geometry"], e["geometry"][1:]))) if ws else None


def page_or_capture(fetched, browser, name, needle):
    """The text of fetch.py's <name>.html when it holds needle, else the
    copy read in Chrome (browser/<name>.txt); with which one it is."""
    p = os.path.join(fetched, f"{name}.html")
    if os.path.exists(p):
        t = text(p)
        if needle in t:
            return t, "fetched"
    b = os.path.join(browser, f"{name}.txt")
    if os.path.exists(b):
        return re.sub(r"\s+", " ", " ".join(l for l in open(b, encoding="utf-8") if not l.startswith("# "))), "browser"
    return None, None


def read_on(browser, name):
    b = os.path.join(browser, f"{name}.txt")
    m = re.search(r"read on (\d{4}-\d\d-\d\d)", open(b, encoding="utf-8").read()) if os.path.exists(b) else None
    return m.group(1) if m else None


def bridges(browser, fetched, out):
    """The Humber Bridge, the Tamar Bridge and the Kiltunnel, per crossing:
    each operator's published prices (fetched, else read in Chrome), at the
    middle of the bridge or the tunnel's toll plaza (bridges-osm.json)."""
    try:
        d = json.load(open(os.path.join(fetched, "bridges-osm.json")))
    except (OSError, ValueError):
        print("Bridges: OpenStreetMap not fetched; not built")
        return
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    vf = "2026-11-13"  # the day the pages were first read; none gives a date

    # Humber Bridge (free-flow, either way).
    t, how = page_or_capture(fetched, browser, "gb-humber", "3 axles or more, over 7.5 tonnes")
    m2 = t and re.search(r"2 axle vehicles between 3\.5 - 7 tonnes[^£]*£([\d.]+)\s*\|?\s*£([\d.]+)", t)
    m3 = t and re.search(r"3 axles or more, over 7\.5 tonnes\s*\|?\s*£([\d.]+)\s*\|?\s*£([\d.]+)", t)
    w = longest(d, r"^Humber Bridge$")
    if not (m2 and m3 and w):
        print(f"Humber Bridge: page or bridge not read ({bool(m2)}, {bool(m3)}, {bool(w)}); not built")
    else:
        lat, lon, _ = middle(w)
        write(out, {"country": "GB", "currency": "GBP", "valid_from": vf, "crossings": True, "osm_extract": stamp,
                    "name": "Humber Bridge toll",
                    "law": (f"Humber Bridge Board's tolls (Humber Bridge Acts 1959 and 2013) per crossing, either way, as published: two-axle vehicles of 3.5-7 t GBP {m2.group(1)}, "
                            f"three axles or more over 7.5 t GBP {m3.group(1)}; with `etc` the account price ({m2.group(2)}, {m3.group(2)}). Two-axle trucks over 7 t are taken at the two-axle price. "
                            "The page gives no date: valid_from is the day it was first read."),
                    "sources": [{"title": "Humber Bridge: Tolls and Ways to Pay" + (" (read in Chrome: tools/tables/browser/gb-humber.txt)" if how == "browser" else ""), "url": "https://www.humberbridge.co.uk/plan-your-trip/tolls-ways-to-pay/"}],
                    "vehicles": "Vehicles over 3.5 t, by axles", "min_kg": 3501,
                    "tolled_roads": "The Humber Bridge (A15), either way.", "point_match_km": 0.15,
                    "toll_points": [{"name": "Humber Bridge", "lat": lat, "lon": lon, "rate": 0, "classes": [
                        {"min_kg": 3501, "max_axles": 2, "rate": float(m2.group(1)), "etc_rate": float(m2.group(2))},
                        {"min_kg": 3501, "min_axles": 3, "rate": float(m3.group(1)), "etc_rate": float(m3.group(2))}]}],
                    "rows": []}, "gb-humber-bridge")

    # Tamar Bridge (charged eastbound, Saltash to Plymouth).
    t, how = page_or_capture(fetched, browser, "gb-tamar", "payable one way, on the trip from Saltash (Cornwall) to Plymouth (Devon)")
    ax = {}
    for n, label in ((2, "2 axles"), (3, "3 axles"), (4, "4\\+ axles")):
        m = t and re.search(r"MGW over 3\.5 tonnes " + label + r" Cash/Card Single £([\d.]+) \+ Trailer £[\d.]+ TamarTag Single £([\d.]+)", t)
        if m:
            ax[n] = (float(m.group(1)), float(m.group(2)))
    w = longest(d, r"^Tamar Bridge$")
    if len(ax) != 3 or not w:
        print(f"Tamar Bridge: page or bridge not read ({sorted(ax)}, {bool(w)}); not built")
    else:
        lat, lon, head = middle(w)
        g = w["geometry"]
        east = bearing((g[0]["lat"], g[0]["lon"]), (g[-1]["lat"], g[-1]["lon"]))
        if not 0 < east < 180:
            east = (east + 180) % 360
        write(out, {"country": "GB", "currency": "GBP", "valid_from": vf, "crossings": True, "osm_extract": stamp,
                    "name": "Tamar Bridge toll",
                    "law": (f"Tamar Bridge and Torpoint Ferry Joint Committee's tolls (Tamar Bridge Acts), payable one way, Saltash (Cornwall) to Plymouth (Devon): vehicles over 3.5 t with 2 axles GBP {ax[2][0]}, "
                            f"3 axles {ax[3][0]}, 4 or more {ax[4][0]} (the 'Single' price; towing a trailer costs double, not modelled); with `etc` the TamarTag price. "
                            "The page gives no date: valid_from is the day it was first read."),
                    "sources": [{"title": "Tamar Crossings: Tamar Bridge Tolls", "url": "https://www.tamarcrossings.org.uk/prices/tamar-bridge-tolls/"}],
                    "vehicles": "Vehicles over 3.5 t, by axles", "min_kg": 3501,
                    "tolled_roads": "The Tamar Bridge (A38), eastbound only.", "point_match_km": 0.15,
                    "toll_points": [{"name": "Tamar Bridge", "lat": lat, "lon": lon, "heading": east, "rate": 0, "classes": [
                        {"min_kg": 3501, "max_axles": 2, "rate": ax[2][0], "etc_rate": ax[2][1]},
                        {"min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": ax[3][0], "etc_rate": ax[3][1]},
                        {"min_kg": 3501, "min_axles": 4, "rate": ax[4][0], "etc_rate": ax[4][1]}]}],
                    "rows": []}, "gb-tamar-bridge")

    # Mersey Gateway and Silver Jubilee bridges (free-flow, either way).
    tr = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribed", "gb-merseyflow-2025.json"), encoding="utf-8"))
    ws = [w for w in (longest(d, r"^Mersey Gateway Bridge$"), longest(d, r"^Silver Jubilee Bridge$")) if w]
    if len(ws) != 2:
        print(f"Mersey bridges: {len(ws)} of the two bridges in OpenStreetMap; not built")
    else:
        c = {x["class"]: x for x in tr["classes"]}
        write(out, {"country": "GB", "currency": "GBP", "valid_from": tr["valid_from"], "crossings": True, "osm_extract": stamp,
                    "name": "Mersey Gateway and Silver Jubilee bridges toll",
                    "law": (f"Halton Borough Council's Road User Charging Scheme Order, toll charges from 1 April 2025 (merseyflow's summary; a table published as an image, transcribed in tools/tables/transcribed/gb-merseyflow-2025.json): "
                            f"per crossing of either bridge, either way, class 3 (3.5-12 t) GBP {c['3']['unregistered']:.2f}, class 4 (over 12 t) GBP {c['4']['unregistered']:.2f} unregistered; "
                            f"with `etc` the sticker-registered price ({c['3']['sticker']:.2f}, {c['4']['sticker']:.2f})."),
                    "sources": [{"title": "merseyflow: Toll charge and scheme detail changed on 1 April 2025", "url": tr["source"]["url"]},
                                {"title": "merseyflow: Toll charges", "url": tr["source"]["page"]}],
                    "vehicles": "Vehicles over 3.5 t (classes 3 and 4)", "min_kg": 3501,
                    "tolled_roads": "The Mersey Gateway Bridge (A533) and the Silver Jubilee Bridge, Runcorn–Widnes, either way.", "point_match_km": 0.15,
                    "toll_points": [{"name": w["tags"]["name"], "lat": middle(w)[0], "lon": middle(w)[1], "rate": 0, "classes": [
                        {"min_kg": 3501, "max_kg": 12000, "rate": c["3"]["unregistered"], "etc_rate": c["3"]["sticker"]},
                        {"min_kg": 12001, "rate": c["4"]["unregistered"], "etc_rate": c["4"]["sticker"]}]} for w in ws],
                    "rows": []}, "gb-mersey-bridges")

    # Kiltunnel (Dordrecht–Hoeksche Waard), either way.
    t, how = page_or_capture(fetched, browser, "nl-kiltunnel", "HOOGTE > 2.30 METER")
    m = t and re.search(r"HOOGTE > 2\.30 METER INCL\. LADING Contant € ?([\d,]+)-?\s*\|?\s*Telecard € ?([\d,]+)", t)
    booths = [e for e in d["elements"] if e["type"] == "node" and e.get("tags", {}).get("barrier") == "toll_booth" and 51.74 < e["lat"] < 51.81 and 4.6 < e["lon"] < 4.7]
    if not m or not booths:
        print(f"Kiltunnel: page or booths not read ({bool(m)}, {len(booths)}); not built")
    else:
        lat, lon = centre(booths)
        cash, tag = num(m.group(1).rstrip(",")), num(m.group(2))
        write(out, {"country": "NL", "currency": "EUR", "valid_from": vf, "crossings": True, "osm_extract": stamp,
                    "name": "Kiltunnel toll",
                    "law": (f"The Kiltunnel's toll (Dordrecht–Hoeksche Waard) per passage, either way, for vehicles over 2.30 m high including load (trucks over 3.5 t are taken to be): EUR {cash:g} cash, "
                            f"with `etc` the Telecard price, EUR {tag:g}. The page gives no date: valid_from is the day it was first read."),
                    "sources": [{"title": "Kiltunnel: Toltarieven", "url": "https://kiltunnel.nl/tarieven"}],
                    "vehicles": "Vehicles over 2.30 m high (here trucks over 3.5 t)", "min_kg": 3501,
                    "tolled_roads": "The Kiltunnel (N217), charged at its toll plaza either way.", "point_match_km": 0.15,
                    "toll_points": [{"name": "Kiltunnel", "lat": lat, "lon": lon, "rate": 0, "classes": [{"min_kg": 3501, "rate": cash, "etc_rate": tag}]}],
                    "rows": []}, "nl-kiltunnel")


def prev_day(d):
    import datetime
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()


def main(transcribed, fetched, out, browser=os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")):
    p = os.path.join(fetched, "tunnels-osm.json")
    d = json.load(open(p))
    osm = d["elements"]
    stamp = d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    herrentunnel(transcribed, out, osm, stamp)
    warnow(browser, out, osm, stamp)
    westerschelde(fetched, out, osm, stamp)
    liefkenshoek(browser, out, osm, stamp)
    gsb(fetched, out, osm, stamp)
    dartford(fetched, out, osm, stamp)
    tyne(fetched, out)
    thames(browser, fetched, out)
    bridges(browser, fetched, out)


if __name__ == "__main__":
    main(*sys.argv[1:])
