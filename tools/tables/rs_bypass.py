"""Builds the Belgrade bypass toll (Obilaznica oko Beograda) from JP Putevi
Srbije's price list for it (fetch.py's rs-obilaznica.pdf, read with
pdftotext -layout: "POSEBNA NAKNADA ZA UPOTREBU JAVNOG PUTA (PUTARINA)",
"važi od", the price in RSD of category 4 per section between two
interchanges) and the motorway in OpenStreetMap (the workflow's
rs-bypass-osm.geojsonseq: motorway ways and junctions by Belgrade, from
Geofabrik's Serbia extract).

Usage: python3 rs_bypass.py fetched/ out-dir -> out-dir/rs-bypass-<date>.json

Only category 4 pays (four or more axles, over 3,500 kg: Putevi Srbije's
categories), by TAG, with no barriers: each section is a toll point in
the middle of each carriageway, paid in that carriageway's direction
(heading), so a route drives past one per section it uses. A section's
carriageway is the shortest way along the A1 (the bypass, "Обилазница око
Београда", and from Batajnica "Милутин Мркоњић") from one interchange's
junction nodes to the other's.
"""
import heapq, json, math, os, re, subprocess, sys

MONTHS = {"januara": 1, "februara": 2, "marta": 3, "aprila": 4, "maja": 5, "juna": 6, "jula": 7, "avgusta": 8,
          "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}
URL = "https://www.putevi-srbije.rs/images/pdf/cene_putarina_obilaznica_lat.pdf"
# The list's interchange names -> OpenStreetMap's (motorway_junction name).
JUNCTIONS = {"BATAJNICA": "Батајница", "BEOGRAD": "Београд", "SURČIN": "Сурчин", "SURČIN JUG": "Сурчин југ",
             "OSTRUŽNICA": "Остружница", "ORLOVAČA": "Орловача", "ORLOVAĆA": "Орловача", "AVALA": "Авала", "BUBANJ POTOK": "Бубањ Поток"}


def label(name):
    """A section end as the list spells it, in title case (ORLOVAĆA is ORLOVAČA)."""
    return {"ORLOVAĆA": "ORLOVAČA"}.get(name, name).title()


def km(a, b):
    """Distance in km between two (lon, lat) points."""
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2)), (a[1] - b[1]) * 110.57)


def bearing(a, b):
    """Degrees clockwise from north, from a to b ((lon, lat))."""
    la1, la2, dl = math.radians(a[1]), math.radians(b[1]), math.radians(b[0] - a[0])
    return round(math.degrees(math.atan2(math.sin(dl) * math.cos(la2), math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl))) % 360, 1)


def main(fetched, out):
    txt = os.path.join(fetched, "rs-obilaznica.txt")
    subprocess.run(["pdftotext", "-layout", os.path.join(fetched, "rs-obilaznica.pdf"), txt], check=True)
    text = open(txt, encoding="utf-8").read()
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"važi od:?\s*(\d+)\.\s*([a-zčćšđž]+)\s+(\d{4})", text)
    if not m or m.group(2) not in MONTHS:
        sys.exit("rs-obilaznica.pdf: no 'važi od' date")
    start = f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    for needle in ("POSEBNA NAKNADA ZA UPOTREBU JAVNOG PUTA (PUTARINA)", "PUTARINA u RSD", "Obilaznica oko Beograda", "K4"):
        if needle not in flat:
            sys.exit(f"rs-obilaznica.pdf no longer says {needle!r}")
    sections = [(int(p), a.strip(), b.strip()) for p, a, b in
                re.findall(r"^\s*(\d+)\s+[as]ekcija:\s*([A-ZČĆŠĐŽ ]+?)\s*-\s*([A-ZČĆŠĐŽ ]+?)\s*$", text, re.M)]
    if len(sections) < 5 or any(a not in JUNCTIONS or b not in JUNCTIONS for _, a, b in sections):
        sys.exit(f"rs-obilaznica.pdf: sections not read ({sections})")
    for (_, _, b), (_, a, _) in zip(sections, sections[1:]):
        if JUNCTIONS[a] != JUNCTIONS[b]:
            sys.exit(f"rs-obilaznica.pdf: the sections don't chain ({b} then {a})")

    # The bypass's carriageways as a directed graph of its nodes (shared coordinates).
    graph, junctions = {}, {}
    for line in open(os.path.join(fetched, "rs-bypass-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if g["type"] == "Point" and p.get("highway") == "motorway_junction" and p.get("name"):
            junctions.setdefault(p["name"], []).append(tuple(g["coordinates"]))
        elif g["type"] == "LineString" and p.get("highway") == "motorway" and "A1" in (p.get("ref") or "").split(";"):
            pts = [tuple(c) for c in g["coordinates"]]
            if p.get("oneway") == "-1":
                pts.reverse()
            pairs = list(zip(pts, pts[1:]))
            if p.get("oneway") not in ("yes", "-1"):
                pairs += [(b, a) for a, b in pairs]
            for a, b in pairs:
                graph.setdefault(a, []).append((b, km(a, b)))

    def way(a, b):
        """The shortest carriageway from junction a's nodes to b's: its points."""
        src, dst = [n for n in junctions.get(a, []) if n in graph], set(junctions.get(b, []))
        dist, prev, heap = {n: 0.0 for n in src}, {}, [(0.0, n) for n in src]
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, math.inf):
                continue
            if n in dst:
                path = [n]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return path[::-1], d
            for m2, w in graph.get(n, []):
                if d + w < dist.get(m2, math.inf):
                    dist[m2], prev[m2] = d + w, n
                    heapq.heappush(heap, (d + w, m2))
        return None, None

    points = []
    for price, a, b in sections:
        for x, y in ((a, b), (b, a)):
            path, length = way(JUNCTIONS[x], JUNCTIONS[y])
            if not path or not 1 < length < 20:
                sys.exit(f"Belgrade bypass: no carriageway from {x} to {y} in OpenStreetMap ({length})")
            half, i = length / 2, 0
            while half > km(path[i], path[i + 1]):
                half -= km(path[i], path[i + 1])
                i += 1
            f = half / km(path[i], path[i + 1])
            at = (path[i][0] + f * (path[i + 1][0] - path[i][0]), path[i][1] + f * (path[i + 1][1] - path[i][1]))
            points.append({"name": f"Obilaznica oko Beograda, sekcija {label(a)} – {label(b)} (towards {label(y)}, {length:.1f} km)",
                           "lat": round(at[1], 6), "lon": round(at[0], 6), "heading": bearing(path[i], path[i + 1]), "rate": 0,
                           "classes": [{"min_kg": 3501, "min_axles": 4, "rate": price}]})
            print(f"{x} -> {y}: {length:.1f} km, {price} RSD, at {at[1]:.5f},{at[0]:.5f} heading {points[-1]['heading']}")
    t = {"country": "RS", "currency": "RSD", "valid_from": start, "crossings": True,
         "osm_extract": open(os.path.join(fetched, "rs-osm-timestamp.txt")).read().strip()[:10],
         "name": "Belgrade bypass toll (Obilaznica oko Beograda), category 4",
         "law": (f"JP Putevi Srbije's price list for the Belgrade bypass from {start} (posebna naknada za upotrebu javnog puta, putarina): "
                 "category 4 (four or more axles, over 3,500 kg) pays per section between two interchanges, in RSD, by TAG without barriers; "
                 "other categories don't pay. Each section is a toll point in the middle of each carriageway, paid in its direction "
                 "(placed on OpenStreetMap's A1 bypass carriageways between the interchanges' junctions)."),
         "sources": [{"title": f"JP Putevi Srbije: Posebna naknada za upotrebu javnog puta (putarina), Obilaznica oko Beograda, važi od {start}", "url": URL},
                     {"title": "JP Putevi Srbije: Kategorizacija vozila/Cenovnik putarine", "url": "https://www.putevi-srbije.rs/index.php/sr/kategorizacija-vozila-cenovnik-putarine"},
                     {"title": "OpenStreetMap (Geofabrik extract), the bypass's carriageways and junctions", "url": "https://download.geofabrik.de/europe/serbia.html"}],
         "vehicles": "Category 4: four or more axles, over 3,500 kg",
         "min_kg": 3501,
         "tolled_roads": "The Belgrade bypass (A1) from Batajnica to Bubanj Potok, by section: " + ", ".join(f"{label(a)} – {label(b)}" for _, a, b in sections) + ".",
         "point_match_km": 0.1,
         "toll_points": points, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"rs-bypass-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(sections), "sections,", len(points), "points")


if __name__ == "__main__":
    main(*sys.argv[1:])
