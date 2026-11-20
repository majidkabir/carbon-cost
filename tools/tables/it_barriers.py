"""Builds Italy's open-system barrier tolls (it-barriers-<date>.json), each
a fixed toll per passage: the Milan ring roads' barriers (Milano
Serravalle - Milano Tangenziali: A50 Terrazzano, A51 Vimercate, A52 Sesto
San Giovanni), from the operator's tables (fetch.py's it-mise-*.txt, PDFs
as text), and the A32 Torino-Bardonecchia's (SITAF: Avigliana, Salbertrand;
the motorway's only toll stations, as it is an open system), from SITAF's
tariffs page (it-sitaf-barriers.html); the barriers' places from OSM
(it-barriers-osm.json around Milan, it-barriers-osm-to.json around Turin).

Usage: python3 it_barriers.py fetched/ out-dir -> out-dir/it-barriers-<date>.json

Prices: each Milan table's "Pedaggio all'utenza" (the toll the user pays,
VAT included, as the main Italian table's rates) of its latest year, and
SITAF's "A32 Toll Tariffs (effective from <date>)" (VAT included: its
Avigliana amounts are SITAF's unit rate, ANAS fee and 22% VAT times the
barrier's 34.47 km), classes B, 3, 4 and 5. Places: the centre of the
barrier's toll booths in OSM, by their name; the A51's Vimercate booths
carry none, so they are the booths within 1 km of the junction OSM names
Vimercate Sud.
"""
import html, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m6toll  # noqa: E402

BARRIERS = [
    # (fetched table, name, motorway, booth name or None, junction near the unnamed booths)
    ("it-mise-terrazzano", "A50 Tangenziale Ovest di Milano, Terrazzano barrier", "A50", "Terrazzano", None),
    ("it-mise-vimercate", "A51 Tangenziale Est di Milano, Vimercate barrier", "A51", None, "Vimercate Sud"),
    ("it-mise-sesto", "A52 Tangenziale Nord di Milano, Sesto San Giovanni barrier", "A52", "Sesto San Giovanni", None),
]
CLASSES = ["A", "B", "3", "4", "5"]
# SITAF's barriers: (name on its page, name, the booths' name in OSM).
SITAF = [
    ("Avigliana", "A32 Torino-Bardonecchia, Avigliana barrier", "Barriera Avigliana"),
    ("Salbertrand", "A32 Torino-Bardonecchia, Salbertrand barrier", "Barriera Salbertrand"),
]
SITAF_PAGE = "https://www.sitaf.it/en/tariffs-and-passes-a32/"


def tolls(text, year=None):
    """The latest year's tolls to the user by class (or the given year's:
    the tables cover several); the year."""
    marks = [(int(m.group(1)), m.end()) for m in re.finditer(r"Tabella pedaggi 1\s*°\s*gennaio\s+(\d{4})", text, re.I)]
    if year:
        marks = [mk for mk in marks if mk[0] == year]
    if not marks:
        sys.exit(f"barrier table: no 'Tabella pedaggi 1° gennaio {year or '<year>'}'")
    year, at = max(marks)
    m = re.search(r"Pedaggio\s+all.{1,2}utenza\s+" + r"\s+".join([r"(\d+,\d\d)"] * 5), text[at:], re.I)
    if not m:
        sys.exit(f"barrier table {year}: no 'Pedaggio all'utenza' row")
    return {c: float(v.replace(",", ".")) for c, v in zip(CLASSES, m.groups())}, year


def sitaf_tolls(page):
    """SITAF's A32 barrier tolls by barrier and class; the year they're
    effective from (1 January)."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " "))
    m = re.search(r"A32 Toll Tariffs \(effective from 01/01/(\d{4})\)", t)
    if not m:
        sys.exit("it-sitaf-barriers: no 'A32 Toll Tariffs (effective from 01/01/<year>)'")
    out = {b: {} for b, _, _ in SITAF}
    for c in CLASSES:
        r = re.search(rf"Class {c} Vehicles " + " ".join(rf"{b}: € (\d+\.\d\d)" for b, _, _ in SITAF), t[m.end():])
        if not r:
            sys.exit(f"it-sitaf-barriers: no class {c} tolls")
        for (b, _, _), v in zip(SITAF, r.groups()):
            out[b][c] = float(v)
    return out, int(m.group(1))


def classes(t):
    return [{"min_kg": 3501, "min_axles": 5, "rate": t["5"]}, {"min_kg": 3501, "min_axles": 4, "rate": t["4"]},
            {"min_kg": 3501, "min_axles": 3, "rate": t["3"]}, {"min_kg": 3501, "rate": t["B"]}]


def place(osm, booth, junction):
    nodes = [e for e in osm["elements"] if e["type"] == "node"]
    if booth:
        ps = [(e["lon"], e["lat"]) for e in nodes if e.get("tags", {}).get("barrier") == "toll_booth" and e["tags"].get("name") == booth]
    else:
        js = [(e["lon"], e["lat"]) for e in nodes if e.get("tags", {}).get("highway") == "motorway_junction" and e["tags"].get("name") == junction]
        ps = [(e["lon"], e["lat"]) for e in nodes if e.get("tags", {}).get("barrier") == "toll_booth" and not e["tags"].get("name")
              and js and min(m6toll.km((e["lon"], e["lat"]), j) for j in js) < 1.0]
    if not ps or max(m6toll.km(p, q) for p in ps for q in ps) > 0.2:
        sys.exit(f"barrier {booth or junction}: {len(ps)} booths, not one plaza")
    return sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)


def main(fetched, out):
    osm = json.load(open(os.path.join(fetched, "it-barriers-osm.json")))
    osm_to = json.load(open(os.path.join(fetched, "it-barriers-osm-to.json")))
    points, years, notes, a32 = [], set(), [], []
    for fid, name, ref, booth, junction in BARRIERS:
        t, year = tolls(open(os.path.join(fetched, fid + ".txt"), encoding="utf-8").read())
        years.add(year)
        lon, lat = place(osm, booth, junction)
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(t)})
        notes.append(f"{name} class 5 EUR {t['5']:.2f}")
        print(name, t, round(lat, 6), round(lon, 6))
    st, year = sitaf_tolls(open(os.path.join(fetched, "it-sitaf-barriers.html"), encoding="utf-8", errors="replace").read())
    years.add(year)
    for b, name, booth in SITAF:
        lon, lat = place(osm_to, booth, None)
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(st[b])})
        a32.append(f"{b} class 5 EUR {st[b]['5']:.2f}")
        print(name, st[b], round(lat, 6), round(lon, 6))
    if len(years) != 1:
        sys.exit(f"barrier tables of different years {sorted(years)}")
    extract = min(o.get("osm3s", {}).get("timestamp_osm_base", "")[:10] for o in (osm, osm_to))
    write(out, years.pop(), points, notes, a32, extract)


def write(out, year, points, notes, a32, osm_extract):
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True,
        "osm_extract": osm_extract,
        "name": "Italian open-system barriers: Milan ring roads (Milano Serravalle - Milano Tangenziali) and the A32 Torino-Bardonecchia (SITAF)",
        "law": (f"A fixed toll to the user per passage by class (A, B by height for two axles; 3, 4, 5 by axles), VAT included, from 1 January {year}. "
                f"Milano Serravalle - Milano Tangenziali's tolls at the barriers of its semi-closed ring roads: "
                + "; ".join(notes) + ". The ring roads' other km carry no toll; the barrier tolls include Autostrade per l'Italia's share where the table gives one. "
                "SITAF's tolls at the A32's two barriers, the open motorway's only toll stations (Avigliana for Rivoli-Susa, Salbertrand for Susa-Bardonecchia): "
                + "; ".join(a32) + " (Avigliana's are SITAF's unit rate per km, ANAS fee and 22% VAT times the barrier's 34.47 km, rounded to 10 cents). "
                "Each barrier is placed at the centre of its toll booths in OpenStreetMap (by name; the Vimercate booths, unnamed, as those within 1 km of the Vimercate Sud junction)."),
        "sources": [{"title": f"Milano Serravalle: tariffe e pedaggi 2022-2026, {n}", "url": u} for n, u in (
            ("barriera di Terrazzano (A50)", "https://www.serravalle.it/uploads/pagine/Tariffe_e_pedaggi_2022_2026_Terrazzano_Tang_OVEST_MI2.pdf"),
            ("barriera di Vimercate (A51)", "https://www.serravalle.it/uploads/pagine/Tariffe_e_pedaggi_2022_2026_Vimercate_Tang_EST_MI6.pdf"),
            ("barriera di Sesto San Giovanni (A52)", "https://www.serravalle.it/uploads/pagine/Tariffe_e_pedaggi_2022_2026_Sesto_SG_Tang_NORD_MI1.pdf"))]
        + [{"title": f"SITAF: A32 tariffs and passes (A32 toll tariffs effective from 01/01/{year})", "url": SITAF_PAGE},
           {"title": "OpenStreetMap (Overpass API): toll booths and the Vimercate junctions around Milan, toll booths around Turin", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Classes B (two axles), 3, 4 and 5 (five axles or more)", "min_kg": 3501,
        "tolled_roads": "A50, A51 and A52 (Milan ring roads): the barriers of Terrazzano, Vimercate and Sesto San Giovanni; A32 Torino-Bardonecchia: the barriers of Avigliana and Salbertrand.",
        "point_match_km": 0.1, "toll_points": points, "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"it-barriers-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
