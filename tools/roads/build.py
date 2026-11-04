"""Builds roads/data/<cc>.json.gz from an OpenStreetMap extract.

Usage: python3 build.py CC ways.geojsonseq out.json.gz

ways.geojsonseq: osmium export of the extract's highway=motorway, trunk
and primary ways with their tags. Each way goes in a class by the rule
for its country (RULES): "mw" are the roads a toll law prices at the
motorway rate, "nat" the other national roads it tolls. Lines are
simplified to SIMPLIFY_M and stored as [lon, lat] * 1e5 integers.
"""
import gzip, json, re, sys
from collections import Counter
from shapely.geometry import LineString

SIMPLIFY_M = 10
# mw: the motorway class of the toll law; nat: the national roads.
RULES = {
    # Czechia, NV 240/2014: dálnice (D) vs silnice I. třídy.
    "CZ": {"mw": r"^D\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Poland, Dz.U. 2026 poz. 33: autostrady and drogi ekspresowe (A, S) vs
    # drogi krajowe.
    "PL": {"mw": r"^[AS]\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Bulgaria, Tarifa art. 25: автомагистрали vs I and II class roads.
    "BG": {"mw": r"^[AА]\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Slovakia, NV 418/2024: diaľnice and rýchlostné cesty (D, R) vs
    # cesty I. triedy.
    "SK": {"mw": r"^[DR]\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Hungary, 25/2013 NFM: gyorsforgalmi utak (M) vs főutak.
    "HU": {"mw": r"^M\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Romania, OMT 1925/2025: autostrăzi and drumuri expres (A, DEx) vs
    # drumuri naționale.
    "RO": {"mw": r"^(A|DEx)\s?\d", "mw_highway": ["motorway"], "nat": r"^(DN\s?)?\d{1,3}[A-Z]{0,2}$"},
}


def classify(rule, tags):
    refs = [r.strip() for r in (tags.get("ref") or "").split(";") if r.strip()]
    if tags.get("highway") in rule["mw_highway"] or any(re.match(rule["mw"], r) for r in refs):
        return "mw"
    if any(re.match(rule["nat"], r) for r in refs):
        return "nat"
    return None


def main(cc, src, dst):
    rule = RULES[cc]
    out = {"mw": [], "nat": []}
    km = Counter()
    refs = Counter()
    for line in open(src, encoding="utf-8"):
        f = json.loads(line.lstrip("\x1e"))
        g, tags = f["geometry"], f["properties"]
        if g["type"] != "LineString" or tags.get("highway", "").endswith("_link"):
            continue
        c = classify(rule, tags)
        refs[(tags.get("highway"), (tags.get("ref") or "")[:6], c)] += 1
        if c is None:
            continue
        ls = LineString(g["coordinates"])
        # Degrees to metres at this latitude, roughly, for the tolerance.
        tol = SIMPLIFY_M / 111_320
        s = ls.simplify(tol, preserve_topology=False)
        pts = [[round(x * 1e5), round(y * 1e5)] for x, y in s.coords]
        if len(pts) >= 2:
            out[c].append([v for p in pts for v in p])
            km[c] += ls.length * 111.32 * 0.68
    with gzip.open(dst, "wt", encoding="utf-8") as fo:
        json.dump({"country": cc, "simplify_m": SIMPLIFY_M, "mw": out["mw"], "nat": out["nat"]}, fo, separators=(",", ":"))
    print(cc, {k: len(v) for k, v in out.items()}, {k: round(v) for k, v in km.items()})
    for (h, r, c), n in refs.most_common(25):
        print(" ", h, r, c, n)


if __name__ == "__main__":
    main(*sys.argv[1:])
