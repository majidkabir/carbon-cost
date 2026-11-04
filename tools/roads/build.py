"""Builds roads/data/<cc>.json.gz from an OpenStreetMap extract.

Usage: python3 build.py CC roads.osm.pbf out.json.gz

roads.osm.pbf: the extract filtered to highway=motorway, trunk and
primary ways (and, for Hungary, the toll section relations tagged
ref:HU:edid with their ways). Each way goes in a class by the rule for
its country (RULES): "mw" are the roads a toll law prices at the
motorway rate, "nat" the other national roads it tolls. In Hungary a way
in a toll section takes its class and suburban share from annex 1 of
25/2013 NFM (hu-annex1.json); "mwf"/"natf" give each line's share, -1
where unknown. Lines are simplified to SIMPLIFY_M and stored as
[lon, lat] * 1e5 integers.
"""
import gzip, json, os, re, sys
from collections import Counter
import osmium
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


class Sections(osmium.SimpleHandler):
    """Way id -> (class, suburban share) from Hungary's toll sections."""

    def __init__(self, annex):
        super().__init__()
        self.annex = annex
        self.ways = {}
        self.found = set()

    def relation(self, r):
        edid = r.tags.get("ref:HU:edid")
        a = self.annex.get(edid)
        if not a:
            return
        self.found.add(edid)
        c = "mw" if a["level"] == "motorway" else "nat"
        for m in r.members:
            if m.type == "w":
                self.ways[m.ref] = (c, a["f"])


class Ways(osmium.SimpleHandler):
    def __init__(self, rule, sections):
        super().__init__()
        self.rule, self.sections = rule, sections
        self.lines = {"mw": [], "nat": []}
        self.shares = {"mw": [], "nat": []}
        self.km = Counter()
        self.refs = Counter()

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        hw = tags.get("highway", "")
        sec = self.sections.get(w.id)
        if sec:
            c, f = sec
        else:
            if hw.endswith("_link") or hw not in ("motorway", "trunk", "primary"):
                return
            c, f = classify(self.rule, tags), -1
        self.refs[(hw, (tags.get("ref") or "")[:6], c, sec is not None)] += 1
        if c is None:
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return
        ls = LineString(coords)
        s = ls.simplify(SIMPLIFY_M / 111_320, preserve_topology=False)
        pts = [[round(x * 1e5), round(y * 1e5)] for x, y in s.coords]
        if len(pts) >= 2:
            self.lines[c].append([v for p in pts for v in p])
            self.shares[c].append(round(f, 3))
            self.km[c] += ls.length * 111.32 * 0.68


def main(cc, src, dst):
    rule = RULES[cc]
    sections = {}
    if cc == "HU":
        rows = json.load(open(os.path.join(os.path.dirname(__file__), "hu-annex1.json")))
        h = Sections({r["id"]: r for r in rows})
        h.apply_file(src)
        sections = h.ways
        print(cc, "toll sections in OSM:", len(h.found), "of", len(rows), "ways:", len(sections))
    h = Ways(rule, sections)
    h.apply_file(src, locations=True)
    out = {"country": cc, "simplify_m": SIMPLIFY_M, "mw": h.lines["mw"], "nat": h.lines["nat"]}
    if sections:
        out["mwf"], out["natf"] = h.shares["mw"], h.shares["nat"]
    with gzip.open(dst, "wt", encoding="utf-8") as fo:
        json.dump(out, fo, separators=(",", ":"))
    print(cc, {k: len(v) for k, v in h.lines.items()}, {k: round(v) for k, v in h.km.items()})
    for k, n in h.refs.most_common(30):
        print(" ", k, n)


if __name__ == "__main__":
    main(*sys.argv[1:])
