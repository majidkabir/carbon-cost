"""Places the stations of pairs.csv on the map, from the French
transport ministry's dataset of toll stations on the conceded national
road network (data.gouv.fr, "Gares de péage du réseau routier national
concédé", Lambert-93 coordinates), else from aliases.json.

Usage: python3 stations.py pairs.csv gares.csv aliases.json osm.geojsonseq stations.json

osm.geojsonseq: OpenStreetMap's French toll booths and motorway junctions
(osmium export), used for names the dataset and aliases.json don't place:
a booth or junction whose name, without "Péage de", "Gare de",
"Barrière de" and the like, is the tariff name.

A tariff name matches a dataset station when, after normalize(), it is
the same name, or the dataset name is the tariff name followed by a
direction or lane word (ENTREE, SORTIE, NORD, SUD, BPV, SENS ...), so
that all the plazas of one station count; aliases.json maps the
remaining tariff names to dataset names by hand. Candidates more than
MAX_KM from the median of the operator's other stations are dropped
(same-named places elsewhere in France). Unplaced names are listed.
"""
import csv, json, re, statistics, sys, unicodedata
from collections import defaultdict
from pyproj import Transformer

MAX_KM = 400
SUFFIX = re.compile(r"^(ENTREE|SORTIE|BPV|SENS|NORD|SUD|EST|OUEST|BARRIERE|BRETELLE|ECHANGEUR|ECH|BAR|PV|A|B|1|2|\d)\b")
ABBR = [(r"\bSTE\b", "SAINTE"), (r"\bST\b", "SAINT"), (r"\bS\b", "SUR"), (r"\bCH\b", "CHATEAU"), (r"\bFAL\b", "FALLAVIER"),
        (r"\bLIM CONC\b", ""), (r"\bB PARIS\b", "BAUDOIN PARIS")]


def normalize(s):
    s = unicodedata.normalize("NFD", s.upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s/(?=\w)", " SUR ", s)
    s = re.sub(r"[()'./,-]", " ", s)
    for a, b in ABBR:
        s = re.sub(a, b, s)
    return re.sub(r"\s+", " ", s).strip()


OSM_PREFIX = re.compile(r"^(PEAGE|GARE|BARRIERE|BARRIERE DE PEAGE|GARE DE PEAGE)( DE| DU| D)? ")


def main(pairs_path, gares_path, aliases_path, osm_path, out):
    to_wgs = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    gares = defaultdict(list)
    for r in csv.DictReader(open(gares_path, encoding="utf-8-sig"), delimiter=";"):
        try:
            lon, lat = to_wgs.transform(float(r["x"].replace(",", ".")), float(r["y"].replace(",", ".")))
        except ValueError:
            continue
        gares[normalize(r["nomGare"])].append({"lat": round(lat, 5), "lon": round(lon, 5), "gare": r["nomGare"], "type": r["typeGare_lib"]})
    aliases = json.load(open(aliases_path, encoding="utf-8"))["aliases"]
    osm = defaultdict(list)
    for line in open(osm_path, encoding="utf-8"):
        f = json.loads(line.lstrip("\x1e"))
        name = f["properties"].get("name")
        if f["geometry"]["type"] != "Point" or not name:
            continue
        lon, lat = f["geometry"]["coordinates"]
        kind = f["properties"].get("barrier") or f["properties"].get("highway")
        osm[OSM_PREFIX.sub("", normalize(name))].append({"lat": round(lat, 5), "lon": round(lon, 5), "gare": "OSM: " + name, "type": kind})
    names = defaultdict(set)
    for r in csv.DictReader(open(pairs_path, encoding="utf-8")):
        for n in (r["entry"], r["exit"]):
            if n != "Système Ouvert":
                names[r["operator"]].add(n)
    placed, missing = {}, []
    for op, ns in names.items():
        found = {}
        for n in sorted(ns):
            keys = [normalize(a) for a in aliases.get(n, [])] or [normalize(n)]
            pts = []
            for k in keys:
                pts += gares.get(k, [])
                if not aliases.get(n):
                    for g, ps in gares.items():
                        if g.startswith(k + " ") and SUFFIX.match(g[len(k) + 1:]):
                            pts += ps
            if not pts:
                for k in keys:
                    pts += osm.get(k, [])
            if pts:
                found[n] = pts
        # Drop same-named stations far from the operator's network.
        lat = statistics.median(p["lat"] for ps in found.values() for p in ps)
        lon = statistics.median(p["lon"] for ps in found.values() for p in ps)
        for n, pts in found.items():
            near = [p for p in pts if ((p["lat"] - lat) * 111) ** 2 + ((p["lon"] - lon) * 75) ** 2 <= MAX_KM ** 2]
            if near:
                placed[n] = sorted({(p["lat"], p["lon"], p["gare"], p["type"]) for p in near})
        missing += [(op, n) for n in sorted(ns) if n not in placed]
    json.dump({n: [{"lat": a, "lon": b, "gare": g, "type": t} for a, b, g, t in v] for n, v in sorted(placed.items())},
              open(out, "w"), ensure_ascii=False, indent=0)
    print(len(placed), "stations placed;", len(missing), "not placed:")
    for op, n in missing:
        print(f"  {op}: {n}")


if __name__ == "__main__":
    main(*sys.argv[1:])
