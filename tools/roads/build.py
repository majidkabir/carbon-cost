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
# Sestri Levante, a closed system). With a fifth element "N", the ways north
# of the junction (its mean latitude): the Autostrada del Brennero's A22
# is a mountain stretch from the Brenner to Affi (Autostrade per l'Italia's
# route calculator: Ala Avio-Affi "5.1 EUR - 28 km", the A22's mountain
# rate; Affi-Verona Nord "2.7 EUR - 17 km", its plain rate).
SPLITS = {"IT": [
    ("SATAP S.p.A.|A4", "Novara Est", (8.6, 45.4, 8.8, 45.55), "Novara Est-Milano"),
    ("CAV S.p.A.|A4", "A57 Venezia", (12.0, 45.4, 12.15, 45.5), "Passante"),
    ("Autostrade per l'Italia S.p.A.|A12", "Civitavecchia Porto", (11.78, 42.15, 11.80, 42.18), "Roma-Civitavecchia"),
    ("Autostrada del Brennero S.p.A.|A22", "Affi-Lago Di Garda Sud", (10.75, 45.52, 10.82, 45.57), "Brennero-Affi", "N"),
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


# Toll motorway OSM tags toll=no: the motorway ways tagged toll=no of an
# "operator|ref" whose every node lies in the box (lon, lat, lon, lat)
# count as tolled (with "|suffix" on their operator key when one is given,
# for a stretch with its own rate). Each is a free stretch at the end of a
# closed system whose barrier or end station charges its km as closed-
# system km, as Autostrade per l'Italia's route calculator and toll form
# count them (tools/tables/browser/it-aspi-routes.txt): Rome's Diramazione
# Roma Nord ("Roma Nord - Ponzano Romano-Soratte 7 EUR - 37 km" from
# Settebagni at the GRA) and Diramazione Roma Sud ("Roma Sud - Valmontone
# 5.7 EUR - 30 km"); the A14's Ravenna branch east of the Ravenna barrier
# ("Barriera Di Ravenna - Imola 7.2 EUR - 38 km" from Ravenna); the A26
# north of the Lago Maggiore station to Gravellona Toce, at ASPI's mountain
# rate ("Lago Maggiore - Arona 7.4 EUR - 33 km" from Gravellona Toce);
# SATAP's A4 from Turin to the Rondissone barrier ("Torino Rondissone -
# Santhia 15.3 EUR - 46 km"); the A1 from Naples to the Napoli Nord barrier
# ("Napoli Nord - Capua 7.9 EUR", 41.5 km at ASPI's rate where the stations
# are 19.6 km apart); the A24 from the Teramo barrier towards the coast
# ("Teramo - San Gabriele Colledara 5.3 EUR - 21 km", the stations 9.5 km
# apart); the A34 from the Villesse barrier to Gorizia ("Barriera Di
# Villesse - Latisana 9.1 EUR - 48 km", about 31 km by the A4); and the A4
# from the Trieste Lisert barrier to Sistiana ("Trieste Lisert - Latisana
# 11 EUR - 58 km", the stations 47.4 km apart).
TOLLED = {"IT": [
    ("Autostrade per l'Italia S.p.A.|A1dir", (12.50, 41.98, 12.62, 42.145), "A1dir Diramazione Roma Nord, GRA-Roma Nord barrier", None),
    ("Autostrade per l'Italia S.p.A.|A1dir", (12.595, 41.82, 12.66, 41.86), "A1dir Diramazione Roma Sud, GRA-Roma Sud barrier", None),
    ("Autostrade per l'Italia S.p.A.|A14dir", (11.905, 44.38, 12.16, 44.435), "A14dir Ravenna-Ravenna barrier", None),
    ("Autostrade per l'Italia S.p.A.|A26", (8.42, 45.774, 8.55, 45.96), "A26 Gravellona Toce-Lago Maggiore", "Lago Maggiore"),
    ("SATAP S.p.A.|A4", (7.70, 45.11, 7.97, 45.245), "A4 Torino-Rondissone barrier", None),
    ("Autostrade per l'Italia S.p.A.|A1", (14.28, 40.84, 14.34, 40.98), "A1 Napoli-Napoli Nord barrier", None),
    ("Strada dei Parchi S.p.A.|A24", (13.716, 42.596, 13.76, 42.67), "A24 Teramo barrier-Teramo", None),
    ("Società Autostrade Alto Adriatico S.p.A.|A34", (13.43, 45.86, 13.61, 45.92), "A34 Villesse barrier-Gorizia", None),
    ("Società Autostrade Alto Adriatico S.p.A.|A4", (13.58, 45.77, 13.645, 45.802), "A4 Trieste Lisert barrier-Sistiana", None),
]}

# Free stretches before a closed system's barrier that OSM tags toll=yes:
# the motorway ways of an "operator|ref" whose every node lies in the box
# don't count as toll motorway. Their barriers charge a fixed toll for
# them and more (it-barriers' closed-system barrier tolls, from
# Autostrade per l'Italia's toll form: tools/tables/browser/
# it-aspi-closed-barriers.txt), so their km mustn't be charged again.
UNTOLLED = {"IT": [
    ("Autostrade per l'Italia S.p.A.|A1", (9.24, 45.3485, 9.31, 45.42), "A1 Milano-Milano Sud barrier"),
    ("Milano Serravalle - Milano Tangenziali S.p.A.|A7", (9.13, 45.3885, 9.18, 45.44), "A7 Milano-Milano Ovest barrier"),
    ("Autostrade per l'Italia S.p.A.|A4", (9.10, 45.50, 9.2688, 45.56), "A4 Milano Ghisolfa-Milano Est barriers"),
    ("Strada dei Parchi S.p.A.|A24", (12.50, 41.90, 12.7033, 41.935), "A24 Roma-Roma Est barrier"),
    ("Autostrade per l'Italia S.p.A.|A16", (14.32, 40.90, 14.4705, 40.93), "A16 Napoli-Napoli Est barrier"),
    ("Autostrade per l'Italia S.p.A.|A30", (14.7273, 40.76, 14.79, 40.7725), "A30 Salerno barrier-Salerno"),
    ("Autostrada del Brennero S.p.A.|A22", (11.42, 46.8856, 11.52, 47.006), "A22 Brenner Pass-Brennero barrier"),
    ("Autostrada dei Fiori S.p.A.|A6", (7.69, 44.8545, 7.76, 44.97), "A6 Torino-Barriera di Torino"),
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
        # TOLLED: (operator|ref, box, label, suffix); km counted in by label.
        self.tolled, self.tolled_km = [], Counter()
        # UNTOLLED: (operator|ref, box, label); km left out by label.
        self.untolled_boxes, self.untolled_km = [], Counter()
        # Toll-rule countries: km of motorway tagged toll=no by operator|ref
        # and 0.05-degree cell, reported where the operator tolls elsewhere.
        self.untolled = Counter()

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        hw = tags.get("highway", "")
        sec = self.sections.get(w.id)
        suffix = None
        if sec:
            c, f = sec
        else:
            if hw.endswith("_link") or hw not in ("motorway", "trunk", "primary"):
                return
            c, f = classify(self.rule, tags), -1
            if c is None and hw == "motorway" and self.tolled and tags.get("toll") == "no":
                key = f"{(tags.get('operator') or '').strip()}|{(tags.get('ref') or '').split(';')[0].strip()}"
                boxes = [(box, lab, suf) for k, box, lab, suf in self.tolled if k == key]
                if boxes:
                    try:
                        pts = [(n.lon, n.lat) for n in w.nodes]
                    except osmium.InvalidLocationError:
                        return
                    hit = [(lab, suf) for (a, b, x1, y1), lab, suf in boxes if pts and all(a <= x <= x1 and b <= y <= y1 for x, y in pts)]
                    if hit and len(pts) >= 2:
                        c, suffix = "mw", hit[0][1]
                        self.tolled_km[hit[0][0]] += LineString(pts).length * 111.32 * 0.68
            if c == "mw" and self.untolled_boxes:
                key = f"{(tags.get('operator') or '').strip()}|{(tags.get('ref') or '').split(';')[0].strip()}"
                boxes = [(box, lab) for k, box, lab in self.untolled_boxes if k == key]
                if boxes:
                    try:
                        pts = [(n.lon, n.lat) for n in w.nodes]
                    except osmium.InvalidLocationError:
                        return
                    hit = [lab for (a, b, x1, y1), lab in boxes if pts and all(a <= x <= x1 and b <= y <= y1 for x, y in pts)]
                    if hit:
                        if len(pts) >= 2:
                            self.untolled_km[hit[0]] += LineString(pts).length * 111.32 * 0.68
                        return
            if c is None and hw == "motorway" and self.rule.get("operator") and tags.get("toll") == "no" and tags.get("operator"):
                try:
                    ls = LineString([(n.lon, n.lat) for n in w.nodes])
                except (osmium.InvalidLocationError, ValueError):
                    return
                p = ls.centroid
                key = f"{tags['operator'].strip()}|{(tags.get('ref') or '').split(';')[0].strip()}"
                self.untolled[(key, round(p.x * 20) / 20, round(p.y * 20) / 20)] += ls.length * 111.32 * 0.74
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
                    if op and suffix:
                        op = f"{op}|{suffix}"
                    elif op in self.split_at and (piece.centroid.y if self.split_at[op][2] else piece.centroid.x) > self.split_at[op][0]:
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
        j = Junctions([sp[:4] for sp in SPLITS[cc]])
        j.apply_file(src)
        for key, name, box, label, *axis in SPLITS[cc]:
            pts = j.found.get(key + "@")
            if not pts:
                sys.exit(f"{cc}: junction {name!r} not found (split of {key})")
            north = axis == ["N"]
            at = sum(p[1 if north else 0] for p in pts) / len(pts)
            h.split_at[key] = (at, label, north)
            print(cc, "split", key, "north of" if north else "east of", name, round(at, 4))
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
    h.untolled_boxes = list(UNTOLLED.get(cc, []))
    h.apply_file(src, locations=True)
    tolling = {op.split("|")[0] for op in h.op_km}
    for (key, x, y), km in sorted(h.untolled.items(), key=lambda kv: -kv[1]):
        if km >= 1 and key.split("|")[0] in tolling:
            print(cc, "motorway tagged toll=no of a tolling operator:", key, f"near {y:.2f},{x:.2f}", round(km, 1), "km")
    for key, box, label, suffix in h.tolled:
        if not h.tolled_km[label]:
            sys.exit(f"{cc}: no toll=no ways of {key} in {box} ({label})")
        print(cc, "counted as toll motorway (both carriageways):", label, round(h.tolled_km[label], 1), "km")
    for key, box, label in h.untolled_boxes:
        print(cc, "left out as free before a barrier (both carriageways):", label, round(h.untolled_km[label], 1), "km")
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
