"""Builds the AP-53 Santiago–Alto de Santo Domingo toll table from the
Ministry of Transport's tolls in force (fetch.py's es-min-ap53-<year>.txt)
and OSM (es-ap53-links-osm.json): a closed system by entry and exit.

Usage: python3 es_ap53.py fetched/ out-dir -> out-dir/es-ap53-<year>-01-01.json

Prices: the first table ("recorridos directos e inversos", with Real
Decreto-ley 20/2022 and the heavy-vehicle bonuses of Real Decreto
276/2025 applied), Pesados 1 and 2, either way, excluding 21% IVA.

Stations, in the table's order along the motorway: Ribadulla and Silleda
at the junction nearest the toll booths of their name ("Peaxe de ...");
Bandeira and the Lalín exits at the junction whose exit is signposted to
them; Santiago at the first junction signposted to Santiago; Alto de Santo
Domingo at the motorway's end. A stretch of carriageway between two
consecutive stations is a station of the system (es_stretch).
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import es_stretch, m6toll  # noqa: E402

VAT = 1.21
ORDER = ["Santiago", "Ribadulla", "Bandeira", "Silleda", "Lalín Oeste", "Lalín Centro", "Lalín Este", "Alto de Santo Domingo"]
FIX = {"Ribadull": "Ribadulla"}  # the table's typo


def pairs(text):
    """{(a, b): (pesados1, pesados2)} with IVA, from the first table."""
    out = {}
    for line in text.split("Descripción de vehículos")[0].splitlines():
        m = re.match(r"^\s*(\S.*?)-(\S.*?)\s{2,}(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s*$", line)
        if m:
            a, b = (FIX.get(x.strip(), x.strip()) for x in m.group(1, 2))
            out[(a, b)] = (float(m.group(4).replace(",", ".")), float(m.group(5).replace(",", ".")))
    return out


def main(fetched, out, year="2026"):
    text = open(os.path.join(fetched, f"es-min-ap53-{year}.txt"), encoding="utf-8").read()
    flat = re.sub(r"\s+", " ", text)
    for need in ("BONIFICACIONES A PESADOS DEL RD 276/2025", "Pesados 1 Camiones y autocares de dos ejes",
                 "Pesados 2 Camiones y autocares, con o sin remolque, con un total de cuatro ejes o más"):
        if need not in flat:
            sys.exit(f"AP-53: the Ministry's table no longer says {need!r}")
    pr = pairs(text)
    names = {x for k in pr for x in k}
    if names != set(ORDER) or len(pr) != 22:
        sys.exit(f"AP-53: {len(pr)} pairs, stations {sorted(names ^ set(ORDER))} changed")

    osm = json.load(open(os.path.join(fetched, "es-ap53-links-osm.json")))
    stamp = osm.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    ls = es_stretch.lines(osm, ["AP-53"])
    juncs, booths = es_stretch.signs(osm), es_stretch.booths(osm)
    keys = {s: es_stretch.plain(s) for s in ORDER}
    match = lambda s, w: re.search(r"\b" + keys[s] + r"\b", w) is not None
    pts = {}
    for line in ls:
        cum = m6toll.along(line)
        got, seq = es_stretch.assign(ORDER[:-1], match, line, cum, juncs, booths)
        if len(got) < len(ORDER) - 1:
            sys.exit(f"AP-53: only {sorted(got)} placed on a carriageway")
        if seq[0] == ORDER[0]:  # the line runs towards Alto de Santo Domingo: its end is the motorway's
            got[ORDER[-1]] = cum[-1]
        else:
            got[ORDER[-1]] = 0.0
        for s, x in got.items():
            pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
    secs = es_stretch.stretches(ls, pts)
    if len(secs) != 2 * (len(ORDER) - 1):
        sys.exit(f"AP-53: {len(secs)} stretches, not {2 * (len(ORDER) - 1)}")

    def price(a, b):
        v = pr.get((a, b)) or pr.get((b, a))
        return v and {"P1": round(v[0] / VAT, 4), "P2": round(v[1] / VAT, 4)}

    g = pr[("Santiago", "Alto de Santo Domingo")]
    cs = es_stretch.system("AP-53", "Ministry of Transport's tolls in force: by entry and exit, either way.", secs, price,
                           [{"name": "P2", "min_kg": 3501, "min_axles": 4}, {"name": "P1", "min_kg": 3501}])
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "crossings": True, "osm_extract": stamp,
        "name": "AP-53 Santiago de Compostela – Alto de Santo Domingo",
        "law": (f"The Ministry of Transport's tolls in force from 1 January {year} on the AP-53, with Real Decreto-ley 20/2022 and the heavy-vehicle bonuses of Real Decreto 276/2025 applied: "
                f"by entry and exit, either way, Pesados 1 (two or three axles) and Pesados 2 (four or more; Santiago – Alto de Santo Domingo EUR {g[1]:.2f} with IVA), excluding 21% IVA. "
                "Stations: each carriageway's stretch between two consecutive entries/exits; Ribadulla and Silleda at the junctions nearest OpenStreetMap's toll booths of their name, "
                "the others at the junctions whose exits are signposted to them, Alto de Santo Domingo at the motorway's end."),
        "sources": [{"title": f"Ministerio de Transportes: peajes vigentes AP-53 {year}", "url": f"https://cdn.transportes.gob.es/portal-web-transportes/carreteras/nuestrared/autopistaspeaje/peajes-actuales/autopista-ap-53,-santiago---alto-de-santo-domingo-{year}.pdf"},
                    {"title": "OpenStreetMap (Overpass API): AP-53 carriageways, junctions, signposted links and toll booths", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Pesados 1: trucks of two or three axles; Pesados 2: four axles or more", "min_kg": 3501,
        "tolled_roads": "AP-53 from Santiago de Compostela to Alto de Santo Domingo.",
        "closed_systems": [cs], "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"es-ap53-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(secs), "stretches,", len(cs["prices"]), "pairs")


if __name__ == "__main__":
    main(*sys.argv[1:])
