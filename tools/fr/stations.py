"""Places the stations of pairs.csv on the map, from the French
transport ministry's dataset of toll stations on the conceded national
road network (data.gouv.fr, "Gares de péage du réseau routier national
concédé", Lambert-93 coordinates), else from aliases.json.

Usage: python3 stations.py pairs.csv gares.csv aliases.json osm.geojsonseq stations.json

osm.geojsonseq: OpenStreetMap's French toll booths and motorway junctions
(osmium export), used for names the dataset and aliases.json don't place:
a booth or junction whose name, without "Péage de", "Gare de",
"Barrière de" and the like, is the tariff name.

A tariff name matches a dataset station when, after normalize(), it
(or one of its variants()) is
the same name, or the dataset name is the tariff name followed by a
direction or lane word (ENTREE, SORTIE, NORD, SUD, BPV, SENS ...), so
that all the plazas of one station count; aliases.json maps the
remaining tariff names to dataset names by hand. "Péage de" and the
like are left off both names when that is what matches. Where a name's
candidates lie more than SPREAD_KM apart (same-named places elsewhere in
France), only those with the most of the operator's other stations
within NEAR_KM are kept. Unplaced names are listed.
"""
import csv, json, math, re, sys, unicodedata
from collections import defaultdict
from pyproj import Transformer

SPREAD_KM = 50
NEAR_KM = 100
SUFFIX = re.compile(r"^(ENTREE|SORTIE|BPV|SENS|VERS|NORD|SUD|EST|OUEST|BARRIERE|BRETELLE|ECHANGEUR|ECH|BAR|PV|A|B|1|2|\d)\b")
ABBR = [(r"\bSTE\b", "SAINTE"), (r"\bST\b", "SAINT"), (r"\bS\b", "SUR"), (r"\bCH\b", "CHATEAU"), (r"\bFAL\b", "FALLAVIER"),
        (r"\bLIM CONC\b", ""), (r"\bB PARIS\b", "BAUDOIN PARIS")]


def normalize(s):
    s = unicodedata.normalize("NFD", s.upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s/(?=\w)", " SUR ", s)
    s = re.sub(r"[()'’./,-]", " ", s)
    for a, b in ABBR:
        s = re.sub(a, b, s)
    return re.sub(r"\s+", " ", s).strip()


OSM_PREFIX = re.compile(r"^(BARRIERE DE PEAGE|GARE DE PEAGE|PEAGE|GARE|BARRIERE)( DES| DE| DU| D)? ")


def variants(name):
    """The normalised forms of a tariff name to look up, in order: as it
    is, without "Péage de" and the like, and for "X (Y)" the Y in
    brackets ("ANGERS (CORZE)", "SAUMUR (VIVY)")."""
    forms = [name]
    m = re.match(r"^.*?\(([^)]*)\)\s*$", name)
    if m:
        forms.append(m.group(1))
    out = []
    for f in forms:
        k = normalize(f)
        out += [k, OSM_PREFIX.sub("", k)]
    return [v for v in dict.fromkeys(out) if v]


def main(pairs_path, gares_path, aliases_path, osm_path, out):
    to_wgs = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    gares = defaultdict(list)
    for r in csv.DictReader(open(gares_path, encoding="utf-8-sig"), delimiter=";"):
        try:
            lon, lat = to_wgs.transform(float(r["x"].replace(",", ".")), float(r["y"].replace(",", ".")))
        except ValueError:
            continue
        p = {"lat": round(lat, 5), "lon": round(lon, 5), "gare": r["nomGare"], "type": r["typeGare_lib"]}
        for k in {normalize(r["nomGare"]), OSM_PREFIX.sub("", normalize(r["nomGare"]))}:
            gares[k].append(p)
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
            keys = [normalize(a) for a in aliases.get(n, [])] or variants(n)
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
        # Same-named stations elsewhere in France: keep the candidates
        # among the most of this operator's other stations.
        def km(p, q):
            return math.hypot((p["lat"] - q["lat"]) * 111, (p["lon"] - q["lon"]) * 111 * math.cos(math.radians(p["lat"])))
        for n, pts in found.items():
            if max(km(p, q) for p in pts for q in pts) > SPREAD_KM:
                score = [sum(any(km(p, q) <= NEAR_KM for q in qs) for m, qs in found.items() if m != n) for p in pts]
                pts = [p for p, sc in zip(pts, score) if sc == max(score)]
            placed[n] = sorted({(p["lat"], p["lon"], p["gare"], p["type"]) for p in pts})
        missing += [(op, n) for n in sorted(ns) if n not in placed]
    json.dump({n: [{"lat": a, "lon": b, "gare": g, "type": t} for a, b, g, t in v] for n, v in sorted(placed.items())},
              open(out, "w"), ensure_ascii=False, indent=0)
    print(len(placed), "stations placed;", len(missing), "not placed:")
    for op, n in missing:
        print(f"  {op}: {n}")


if __name__ == "__main__":
    main(*sys.argv[1:])
