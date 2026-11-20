"""Builds roads/data/<cc>.json.gz from an OpenStreetMap extract.

Usage: OSM_EXTRACT=<extract timestamp> python3 build.py CC roads.osm.pbf out.json.gz

roads.osm.pbf: the extract filtered to highway=motorway, trunk and
primary ways (and, for Hungary, the toll section relations tagged
ref:HU:edid with their ways). Each way goes in a class by the rule for
its country (RULES; in Italy the motorways tagged toll=yes, each with its
operator tag): "mw" are the roads a toll law prices at the
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
    # Italy: the toll motorways (autostrade a pedaggio), the ways tagged
    # toll=yes; the toll-free ones (A2, A19, A29, ring roads) aren't.
    # Each line keeps its way's operator tag (the concession) and first
    # ref, as "operator|ref", in "ops" and "mwop" (an index into ops per mw
    # line, -1 for none).
    "IT": {"mw": r"^A\d", "mw_highway": ["motorway"], "nat": r"^$a", "toll": True, "operator": True},
    # Belarus: the BelToll roads (the list of the Regulation approved by
    # Council of Ministers resolution No. 340), the motorway, trunk and
    # primary ways tagged toll=yes or toll:hgv=yes.
    "BY": {"mw": r"^$a", "mw_highway": [], "nat": r"^$a", "toll": True, "toll_highway": ["motorway", "trunk", "primary"]},
}


def classify(rule, tags):
    if rule.get("toll"):
        tolled = tags.get("toll") == "yes" or tags.get("toll:hgv") == "yes"
        return "mw" if tags.get("highway") in rule.get("toll_highway", ["motorway"]) and tolled else None
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


# Stretches a concession prices apart from the rest of its motorway: the
# ways of an operator key east of a named motorway junction (the mean
# longitude of the junction nodes of that name in the box) get the key
# "operator|ref|label". SATAP's A4 charges its tariff B from Novara Est to
# Milan; CAV's A4 is the stretch Padova Est-A4/A57 interchange and, east
# of the interchange (OSM "A57 Venezia"), the Passante di Mestre. Autostrade
# per l'Italia's A12 east of the Civitavecchia Porto junction is the open
# Roma-Civitavecchia, charged at its barriers (its other A12 is Genova-
# Sestri Levante, a closed system).
SPLITS = {"IT": [
    ("SATAP S.p.A.|A4", "Novara Est", (8.6, 45.4, 8.8, 45.55), "Novara Est-Milano"),
    ("CAV S.p.A.|A4", "A57 Venezia", (12.0, 45.4, 12.15, 45.5), "Passante"),
    ("Autostrade per l'Italia S.p.A.|A12", "Civitavecchia Porto", (11.78, 42.15, 11.80, 42.18), "Roma-Civitavecchia"),
]}


# Concession motorway stretches a country's toll law leaves to their
# operators (Poland's e-TOLL doesn't charge them: www.gov.pl/web/infrastruktura/
# platnosci-za-przejazdy-drogowe): the ways of the ref between two motorway
# junctions (the mean position of the junction nodes of each name in its
# box; None: the motorway's end in the country, the state border) are left
# out. The stretch runs along the axis on which its ends lie further apart.
FREE = {"PL": [
    ("A4", "Murckowska", (18.95, 50.15, 19.15, 50.30), "Balice I", (19.70, 50.0, 19.90, 50.15), "A4 Katowice-Kraków (Stalexport Autostrada Małopolska)"),
    ("A2", None, (14.50, 52.2, 14.75, 52.45), "Modła", (18.05, 52.15, 18.35, 52.35), "A2 Świecko-Konin (Autostrada Wielkopolska)"),
    ("A1", "Rusocin", (18.45, 54.15, 18.75, 54.35), "Toruń Południe", (18.50, 52.90, 18.80, 53.05), "A1 Rusocin-Toruń (AmberOne)"),
]}


# Toll motorway OSM tags toll=no: the motorway ways of an "operator|ref"
# whose every node lies in the box (lon, lat, lon, lat) count as tolled.
# Rome's branches whose barrier charges the km from the GRA as closed-
# system km (Autostrade per l'Italia's route calculator, tools/tables/
# browser/it-aspi-routes.txt): the Diramazione Roma Nord (A1dir) to the
# Roma Nord barrier ("Roma Nord - Ponzano Romano-Soratte 7 EUR - 37 km"
# from Settebagni), most of whose ways OSM tags toll=no; the Diramazione
# Roma Sud (A1dir) to the Roma Sud barrier ("Roma Sud - Valmontone 5.7 EUR
# - 30 km") and the A24 to the Roma Est barrier ("Roma Est - Tivoli 5.3 EUR
# - 21 km" from Settecamini), one carriageway of each tagged toll=no for
# 3-4 km.
TOLLED = {"IT": [
    ("Autostrade per l'Italia S.p.A.|A1dir", (12.50, 41.98, 12.62, 42.145), "A1dir Diramazione Roma Nord, GRA-Roma Nord barrier"),
    ("Autostrade per l'Italia S.p.A.|A1dir", (12.595, 41.82, 12.66, 41.86), "A1dir Diramazione Roma Sud, GRA-Roma Sud barrier"),
    ("Strada dei Parchi S.p.A.|A24", (12.60, 41.91, 12.705, 41.935), "A24 Roma, GRA-Roma Est barrier"),
]}


class Junctions(osmium.SimpleHandler):
    def __init__(self, splits):
        super().__init__()
        self.splits, self.found = splits, {}

    def node(self, n):
        if n.tags.get("highway") != "motorway_junction":
            return
        x, y = n.location.lon, n.location.lat
        for key, name, (a, b, c, d), label in self.splits:
            if n.tags.get("name") == name and a <= x <= c and b <= y <= d:
                self.found.setdefault(key, []).append(x)
                self.found.setdefault(key + "@", []).append((x, y))


class Ways(osmium.SimpleHandler):
    def __init__(self, rule, sections, urban=None):
        super().__init__()
        self.rule, self.sections, self.urban = rule, sections, urban
        self.urban_km = 0.0
        self.lines = {"mw": [], "nat": []}
        self.shares = {"mw": [], "nat": []}
        self.km = Counter()
        self.refs = Counter()
        self.ops, self.op_index, self.mwop, self.op_km = [], {}, [], Counter()
        self.split_at = {}
        # FREE stretches: (ref, axis, low, high, label); km left out by label.
        self.free, self.free_km = [], Counter()
        # TOLLED: (operator|ref, box, label); km counted in by label.
        self.tolled, self.tolled_km = [], Counter()

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
            if c is None and hw == "motorway" and self.tolled:
                key = f"{(tags.get('operator') or '').strip()}|{(tags.get('ref') or '').split(';')[0].strip()}"
                boxes = [(box, lab) for k, box, lab in self.tolled if k == key]
                if boxes:
                    try:
                        pts = [(n.lon, n.lat) for n in w.nodes]
                    except osmium.InvalidLocationError:
                        return
                    hit = [lab for (a, b, x1, y1), lab in boxes if pts and all(a <= x <= x1 and b <= y <= y1 for x, y in pts)]
                    if hit and len(pts) >= 2:
                        c = "mw"
                        self.tolled_km[hit[0]] += LineString(pts).length * 111.32 * 0.68
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
        if c == "mw" and self.free:
            refs = [r.strip() for r in (tags.get("ref") or "").split(";")]
            p = ls.centroid
            hit = [lab for ref, axis, lo, hi, lab in self.free if ref in refs and lo <= (p.x, p.y)[axis] <= hi]
            if hit:
                self.free_km[hit[0]] += ls.length * 111.32 * 0.68
                return
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
                if c == "mw" and self.rule.get("operator"):
                    op = (tags.get("operator") or "").strip()
                    ref = (tags.get("ref") or "").split(";")[0].strip()
                    op = f"{op}|{ref}" if op else ""
                    if op in self.split_at and piece.centroid.x > self.split_at[op][0]:
                        op = f"{op}|{self.split_at[op][1]}"
                    if op and op not in self.op_index:
                        self.op_index[op] = len(self.ops)
                        self.ops.append(op)
                    self.mwop.append(self.op_index.get(op, -1))
                    self.op_km[op] += piece.length * 111.32 * 0.68


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
    if SPLITS.get(cc):
        j = Junctions(SPLITS[cc])
        j.apply_file(src)
        for key, name, box, label in SPLITS[cc]:
            xs = j.found.get(key)
            if not xs:
                sys.exit(f"{cc}: junction {name!r} not found (split of {key})")
            h.split_at[key] = (sum(xs) / len(xs), label)
            print(cc, "split", key, "east of", name, round(sum(xs) / len(xs), 4))
    if FREE.get(cc):
        spec = [(f"{ref}|{i}", name, box, label) for ref, n1, b1, n2, b2, label in FREE[cc] for i, name, box in ((0, n1, b1), (1, n2, b2)) if name]
        j = Junctions(spec)
        j.apply_file(src)
        for ref, n1, b1, n2, b2, label in FREE[cc]:
            ends = []
            for i, name, box in ((0, n1, b1), (1, n2, b2)):
                if name is None:
                    ends.append(None)
                    continue
                pts = j.found.get(f"{ref}|{i}@")
                if not pts:
                    sys.exit(f"{cc}: junction {name!r} not found (end of {label})")
                ends.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
            known = [e for e in ends if e]
            if len(known) == 2:
                axis = 0 if abs(known[0][0] - known[1][0]) * 0.65 > abs(known[0][1] - known[1][1]) else 1
                lo, hi = sorted((known[0][axis], known[1][axis]))
            else:
                # One end is the border: the box of the other end says which way.
                (e,) = known
                bx = b1 if ends[0] is None else b2
                mid = ((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
                axis = 0 if abs(mid[0] - e[0]) * 0.65 > abs(mid[1] - e[1]) else 1
                lo, hi = sorted((e[axis], -1e9 if mid[axis] < e[axis] else 1e9))
            h.free.append((ref, axis, lo, hi, label))
            print(cc, "left out:", label, "axis", "xy"[axis], round(lo, 4), round(hi, 4), ends)
    h.tolled = list(TOLLED.get(cc, []))
    h.apply_file(src, locations=True)
    for key, box, label in h.tolled:
        if not h.tolled_km[label]:
            sys.exit(f"{cc}: no toll=no ways of {key} in {box} ({label})")
        print(cc, "counted as toll motorway (both carriageways):", label, round(h.tolled_km[label], 1), "km")
    for label, km in h.free_km.items():
        print(cc, "left out km (both carriageways):", label, round(km))
    if urban is not None:
        print(cc, "national road km left out inside municipalities (both carriageways):", round(h.urban_km))
    out = {"country": cc, "simplify_m": SIMPLIFY_M, "mw": h.lines["mw"], "nat": h.lines["nat"]}
    # The extract's date (the workflow passes its osmosis_replication_timestamp).
    if os.environ.get("OSM_EXTRACT"):
        out["osm_extract"] = os.environ["OSM_EXTRACT"][:10]
    if sections:
        out["mwf"], out["natf"] = h.shares["mw"], h.shares["nat"]
    if h.free:
        # The stretches left out, by name: the tool says the km it counts
        # as local roads include them.
        out["left_out"] = sorted({label for *_, label in h.free})
    if rule.get("operator"):
        out["ops"], out["mwop"] = h.ops, h.mwop
        for op, km in h.op_km.most_common():
            print("  operator", repr(op), round(km))
    with gzip.open(dst, "wt", encoding="utf-8") as fo:
        json.dump(out, fo, separators=(",", ":"))
    print(cc, {k: len(v) for k, v in h.lines.items()}, {k: round(v) for k, v in h.km.items()})
    for k, n in h.refs.most_common(30):
        print(" ", k, n)


if __name__ == "__main__":
    main(*sys.argv[1:])
