"""Builds roads/data/<cc>.json.gz from an OpenStreetMap extract.

Usage: OSM_EXTRACT=<extract timestamp> python3 build.py CC roads.osm.pbf out.json.gz

roads.osm.pbf: the extract filtered to highway=motorway, trunk and
primary ways (and, for Hungary, the toll section relations tagged
ref:HU:edid with their ways). Each way goes in a class by the rule for
its country (RULES): "mw" are the roads a toll law prices at the
motorway rate, "nat" the other national roads it tolls. In Hungary a way
in a toll section takes its class and suburban share from annex 1 of
25/2013 NFM (hu-annex1.json, from tools/tables/hu.py); "mwf"/"natf" give each line's share, -1
where unknown. Lines are simplified to SIMPLIFY_M and stored as
[lon, lat] * 1e5 integers.

For Romania, a fourth argument gives an extract of the administrative
boundaries and built-up land use: national roads inside the built-up
area of a municipality (municipiu: in OpenStreetMap an administrative
boundary named "Municipiul ..." or tagged place=city) aren't tolled (Legea 226/2023, SETRE
România), so those stretches are left out of "nat". The built-up area
is the municipality's residential, commercial, industrial and retail
land, 50 m around.
"""
import gzip, json, os, re, sys
from collections import Counter
import osmium
from shapely import wkb
from shapely.geometry import LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

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


class Urban(osmium.SimpleHandler):
    """Municipalities' boundaries and built-up land use."""

    def __init__(self):
        super().__init__()
        self.wkb = osmium.geom.WKBFactory()
        self.towns, self.land = [], []
        self.seen = Counter()

    def area(self, a):
        t = a.tags
        if t.get("boundary") == "administrative":
            self.seen[(t.get("admin_level"), (t.get("name") or "").split(" ")[0][:12], t.get("place"), t.get("border_type"))] += 1
        try:
            if t.get("boundary") == "administrative" and ((t.get("name") or "").startswith("Municipiul ") or t.get("place") == "city"
                                                            or t.get("border_type") in ("municipality", "municipiu")):
                self.towns.append(wkb.loads(self.wkb.create_multipolygon(a), hex=True))
            elif t.get("landuse") in ("residential", "commercial", "industrial", "retail"):
                self.land.append(wkb.loads(self.wkb.create_multipolygon(a), hex=True))
        except Exception:
            pass

    def built_up(self):
        tree = STRtree(self.land)
        parts = []
        for town in self.towns:
            hits = [self.land[i] for i in tree.query(town, predicate="intersects")]
            if hits:
                parts.append(unary_union([h.buffer(0.0005) for h in hits]).intersection(town))
        return unary_union(parts) if parts else None


class Ways(osmium.SimpleHandler):
    def __init__(self, rule, sections, urban=None):
        super().__init__()
        self.rule, self.sections, self.urban = rule, sections, urban
        self.urban_km = 0.0
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
        pieces = [ls]
        if c == "nat" and self.urban is not None and ls.intersects(self.urban):
            rest = ls.difference(self.urban)
            self.urban_km += (ls.length - rest.length) * 111.32 * 0.68
            pieces = [g for g in getattr(rest, "geoms", [rest]) if g.geom_type == "LineString" and not g.is_empty]
        for piece in pieces:
            s = piece.simplify(SIMPLIFY_M / 111_320, preserve_topology=False)
            pts = [[round(x * 1e5), round(y * 1e5)] for x, y in s.coords]
            if len(pts) >= 2:
                self.lines[c].append([v for p in pts for v in p])
                self.shares[c].append(round(f, 3))
                self.km[c] += piece.length * 111.32 * 0.68


def main(cc, src, dst, areas=None):
    rule = RULES[cc]
    urban = None
    if areas:
        u = Urban()
        u.apply_file(areas, locations=True)
        urban = u.built_up()
        print(cc, "municipalities (place=city):", len(u.towns), "built-up polygons:", len(u.land))
        for k, n in u.seen.most_common(40):
            print("  boundary", k, n)
    sections = {}
    if cc == "HU":
        rows = json.load(open(os.path.join(os.path.dirname(__file__), "hu-annex1.json")))
        h = Sections({r["id"]: r for r in rows})
        h.apply_file(src)
        sections = h.ways
        print(cc, "toll sections in OSM:", len(h.found), "of", len(rows), "ways:", len(sections))
    h = Ways(rule, sections, urban)
    h.apply_file(src, locations=True)
    if urban is not None:
        print(cc, "national road km left out inside municipalities (both carriageways):", round(h.urban_km))
    out = {"country": cc, "simplify_m": SIMPLIFY_M, "mw": h.lines["mw"], "nat": h.lines["nat"]}
    # The extract's date (the workflow passes its osmosis_replication_timestamp).
    if os.environ.get("OSM_EXTRACT"):
        out["osm_extract"] = os.environ["OSM_EXTRACT"][:10]
    if sections:
        out["mwf"], out["natf"] = h.shares["mw"], h.shares["nat"]
    with gzip.open(dst, "wt", encoding="utf-8") as fo:
        json.dump(out, fo, separators=(",", ":"))
    print(cc, {k: len(v) for k, v in h.lines.items()}, {k: round(v) for k, v in h.km.items()})
    for k, n in h.refs.most_common(30):
        print(" ", k, n)


if __name__ == "__main__":
    main(*sys.argv[1:])
