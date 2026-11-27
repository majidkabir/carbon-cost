"""Builds roads/data/<cc>.json.gz from an OpenStreetMap extract.

Usage: OSM_EXTRACT=<extract timestamp> python3 build.py CC roads.osm.pbf out.json.gz

roads.osm.pbf: the extract filtered to highway=motorway, trunk and
primary ways (and, for Hungary, the toll section relations tagged
ref:HU:edid with their ways). Each way goes in a class by the rule for
its country (RULES; in Italy the motorways tagged toll=yes, each with its
operator tag): "mw" are the roads a toll law prices at the
motorway rate, "nat" the other national roads it tolls (in Germany and
Austria, whose rates are the same on both, only tolled or not counts). In Hungary a way
in a toll section takes its class and suburban share from annex 1 of
25/2013 NFM (hu-annex1.json, from tools/tables/hu.py); "mwf"/"natf" give each line's share, -1
where unknown. A Hungarian way in no toll section is tolled only as one of
one: the other carriageway (within TWIN_M of a section way of its road
number along its length), or a hole or gap in the sections' relations: a
chain of such ways of the road whose ends meet section ways of the road,
where annex 1 runs on between them (but for a junction's JOIN_KM), and
whose km (one carriageway: a oneway way counts half) the annex km OSM's
relations lack there leave room for (ROOM, ROOM_KM). It takes the class
and share of the section it is in, of the annex's sections between, or
where two meet in it, their mean share. The other ways, such as an old
road beside a section OSM has whole, and the other main roads and
motorways, such as those inside
Budapest or between two sections annex 1 doesn't join, aren't tolled. Lines are
simplified to SIMPLIFY_M and stored as [lon, lat] * 1e5 integers.

In Czechia a way of the main roads (secondary included) is tolled where
the toll operator's map draws a layer at its points, in that layer's
class (cz_myto.py: tools/tables/browser/cz-myto-wms.json, read at the
points of cz-samples.json.gz), but not where it runs beside a road of
that class the line is drawn for; the build writes the samples for the
next reading beside its output, and checks each class's tolled km against
the law's (cz-network.json).

In Bulgaria the class I and II roads are tolled where the toll segments
of the list run (bg_network.py, bg-network.json), found along the roads
by bgseg.py; the settlements between them aren't; the motorways all are.

For Hungary, a fourth argument gives an extract of the administrative
boundaries, for Budapest's. For Romania, a fourth argument gives an extract of the administrative
boundaries and built-up land use: national roads inside the built-up
area of a municipality (municipiu: in OpenStreetMap an administrative
boundary named "Municipiul ..." or tagged place=city) aren't tolled (Legea 226/2023, SETRE
România), so those stretches are left out of "nat". The built-up area
is the municipality's residential, commercial, industrial and retail
land, 50 m around.
"""
import gzip, json, math, os, re, sys
from collections import Counter
import osmium
import bgseg
import cz_myto
from shapely import wkb
from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

SIMPLIFY_M = 10
# Hungary: a way outside the toll sections within TWIN_M of a section way
# of its road along its length is that section's other carriageway; a chain
# of such ways (joined within BRIDGE_M: carriageways, roundabouts) whose
# ends meet section ways of its road within BRIDGE_M, a gap in OSM's
# relations (up to GAP_KM more than 1.3 times the annex's km between them)
# or a break.
TWIN_M, GAP_KM, BRIDGE_M = 60, 10, 60
# Unlisted km between two of annex 1's sections a gap may run across (a
# junction's; 32u9k695m ends at 10+463, 32u10k510m starts at 10+510).
JOIN_KM = 0.1
# A chain fills a hole or gap in the sections' relations if its km (one
# carriageway) are at most ROOM times the annex km OSM's relations lack
# there, plus ROOM_KM (OSM's lengths and the annex's differ a little).
ROOM, ROOM_KM = 1.3, 0.3
# A road whose toll sections OSM has for this share of annex 1's km (both
# carriageways of an M road): its other ways are left out.
COVERED = 0.9
# Roads whose chains the build decides it lists (ROADS_DEBUG="21,4", or "*"
# for all).
DEBUG_ROADS = set(filter(None, os.environ.get("ROADS_DEBUG", "").split(",")))
# mw: the motorway class of the toll law; nat: the national roads.
RULES = {
    # Czechia, NV 240/2014: dálnice (D) vs silnice I. třídy; tolled only
    # where vyhláška č. 470/2012 Sb. lists them, as the operator's map
    # draws them (cz_myto.py).
    "CZ": {"mw": r"^D\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$", "myto": True},
    # Poland, Dz.U. 2026 poz. 33: autostrady and drogi ekspresowe (A, S) vs
    # drogi krajowe.
    "PL": {"mw": r"^[AS]\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Bulgaria, Tarifa art. 25: автомагистрали vs I and II class roads,
    # those by the toll segments of the list (bg_network.py, bgseg.py).
    "BG": {"mw": r"^[AА]\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$", "segments": "bg-network.json"},
    # Slovakia, NV 418/2024: diaľnice and rýchlostné cesty (D, R) vs
    # cesty I. triedy.
    "SK": {"mw": r"^[DR]\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$"},
    # Hungary, 25/2013 NFM: gyorsforgalmi utak (M) vs főutak.
    "HU": {"mw": r"^M\d", "mw_highway": ["motorway"], "nat": r"^\d{1,2}$", "sections_only": True},
    # Romania, OMT 1925/2025: autostrăzi and drumuri expres (A, DEx) vs
    # drumuri naționale.
    "RO": {"mw": r"^(A|DEx)\s?\d", "mw_highway": ["motorway"], "nat": r"^(DN\s?)?\d{1,3}[A-Z]{0,2}$"},
    # Italy: the toll motorways (autostrade a pedaggio), the ways tagged
    # toll=yes; the toll-free ones (A2, A19, A29, ring roads) aren't.
    # Each line keeps its way's operator tag (the concession) and first
    # ref, as "operator|ref", in "ops" and "mwop" (an index into ops per mw
    # line, -1 for none).
    "IT": {"mw": r"^A\d", "mw_highway": ["motorway"], "nat": r"^$a", "toll": True, "operator": True},
    # Germany, BFStrMG § 1 (1): Bundesautobahnen (A) and Bundesstraßen (B);
    # the rates don't differ between them.
    "DE": {"mw": r"^A\s?\d", "mw_highway": ["motorway"], "nat": r"^B\s?\d"},
    # Austria, BStMG § 1: Bundesstraßen with a toll, the Autobahnen (A) and
    # Schnellstraßen (S); one rate for both.
    "AT": {"mw": r"^A\s?\d", "mw_highway": ["motorway"], "nat": r"^S\s?\d"},
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
                self.ways[m.ref] = (c, a["f"], a["road"], edid)


class Boundary(osmium.SimpleHandler):
    """An administrative area by name, its polygons."""

    def __init__(self, name):
        super().__init__()
        self.wkb = osmium.geom.WKBFactory()
        self.name, self.parts = name, []

    def area(self, a):
        t = a.tags
        if t.get("boundary") == "administrative" and t.get("name") == self.name and a.from_way() is False:
            try:
                self.parts.append(wkb.loads(self.wkb.create_multipolygon(a), hex=True))
            except Exception:
                pass


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
],
    # BFStrMG § 1 (3) 1 and 2: no toll on the A 6 from the French border to
    # the Saarbrücken-Fechingen junction, nor on the A 5 from the Swiss
    # and French borders to the Müllheim/Neuenburg junction.
    "DE": [
    ("A 6", None, (6.93, 49.17, 7.00, 49.23), "Saarbrücken-Fechingen", (7.03, 49.17, 7.13, 49.24), "A 6 French border-Saarbrücken-Fechingen (BFStrMG § 1 (3) 1)"),
    ("A 5", None, (7.55, 47.54, 7.66, 47.62), "Müllheim / Neuenburg", (7.53, 47.77, 7.66, 47.85), "A 5 Swiss and French borders-Müllheim/Neuenburg (BFStrMG § 1 (3) 2)"),
]}

# Sections of a country's tolled roads that a private operator tolls
# instead (Germany, BFStrMG § 1 (3) 3: the tunnels tolled under § 2
# FStrPrivFinG, priced as crossings): the ways of the ref tagged toll=yes
# whose every node lies in the box are left out.
PRIVATE = {"DE": [
    ("B 105", (12.00, 54.10, 12.20, 54.20), "Warnowtunnel (B 105, FStrPrivFinG)"),
    ("B 75", (10.70, 53.85, 10.90, 53.95), "Herrentunnel (B 75, FStrPrivFinG)"),
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

# Autostrade per l'Italia's mountain stretches inside a road it also runs
# on the plain: the ways of an "operator|ref" whose centroid lies in the box
# get "|mountain" on their key (priced at ASPI's mountain rate). Its route
# calculator prices them at that rate (tools/tables/browser/
# it-aspi-mountain.txt): the A1 across the Apennines from Bologna to
# Calenzano (Sasso Marconi-Barberino di Mugello 55 km EUR 12.30), the A26
# from Genova Voltri to Alessandria Sud (Ovada-Alessandria Sud 33 km EUR
# 7.40; Vercelli Est-Romagnano 30 km EUR 5.70, the plain rate), the A23
# from Carnia to Tarvisio (Carnia-Pontebba 35 km EUR 7.90; Gemona-Carnia
# 16 km EUR 3.00, the plain rate), the A16 from Baiano to Candela (Avellino
# Est-Grottaminarda 33 km EUR 7.40, Grottaminarda-Lacedonia 30 km EUR
# 6.70; Tufino-Avellino Ovest and Lacedonia-Cerignola Ovest mixed), the A27
# from about Conegliano to Belluno (Vittorio Veneto Sud-Fadalto 16 km EUR
# 3.60, Belluno-Vittorio Veneto Sud 31 km EUR 7.00; Treviso Nord-Vittorio
# Veneto Sud 30 km EUR 6.10, its last 11 km mountain). Its
# A7, A10 and A12 by Genoa are mountain
# throughout and priced so by key (tools/tables/it.py).
MOUNTAIN = {"IT": [
    ("Autostrade per l'Italia S.p.A.|A1", (11.0, 43.855, 11.40, 44.50), "A1 Bologna-Calenzano"),
    ("Autostrade per l'Italia S.p.A.|A26", (8.40, 44.40, 8.80, 44.874), "A26 Genova Voltri-Alessandria Sud"),
    ("Autostrade per l'Italia S.p.A.|A23", (12.90, 46.37, 13.70, 46.56), "A23 Carnia-Tarvisio"),
    ("Autostrade per l'Italia S.p.A.|A16", (14.60, 40.80, 15.527, 41.25), "A16 Baiano-Candela"),
    ("Autostrade per l'Italia S.p.A.|A27", (12.15, 45.87, 12.45, 46.25), "A27 Conegliano-Belluno"),
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
    # CAV's A57 from the A4/Passante junction to the Venezia Mestre barrier:
    # free between its stations (the route calculator's Spinea-Venezia
    # Mestre via Mira-Oriago "0 EUR - 0 km"); one toll from Padova Est to
    # any of them, charged at a point by the junction (it-barriers).
    ("CAV S.p.A.|A57", (12.08, 45.44, 12.20, 45.48), "A57 Mirano Dolo-Venezia Mestre barrier"),
    ("Società Autostrade Alto Adriatico S.p.A.|A57", (12.30, 45.55, 12.3350, 45.58), "A57 Mestre-Venezia Est barrier"),
    ("Società di Progetto Brebemi S.p.A|A35", (9.9612, 45.50, 9.98, 45.54), "A35 Castegnato link-Chiari Est barrier"),
    ("Società Autostrade Alto Adriatico S.p.A.|A28", (12.4795, 45.79, 12.8245, 45.93), "A28 Portogruaro-Cordignano barrier"),
    ("Autostrade per l'Italia S.p.A.|A8/A26", (8.7763, 45.66, 8.81, 45.70), "A8/A26 Gallarate-Gallarate Ovest barrier"),
    ("Autostrada Asti-Cuneo S.p.A.|A33", (7.50, 44.35, 7.6089, 44.45), "A33 Cuneo-Castelletto Stura barrier"),
    ("SAT p.A.|A12", (10.45, 43.30, 10.56, 43.3693), "A12 San Pietro in Palazzi-Rosignano barrier"),
]}


class Junctions(osmium.SimpleHandler):
    def __init__(self, splits):
        super().__init__()
        self.splits, self.found, self.seen = splits, {}, {}

    def node(self, n):
        if n.tags.get("highway") != "motorway_junction":
            return
        x, y = n.location.lon, n.location.lat
        for key, name, (a, b, c, d), label in self.splits:
            if a <= x <= c and b <= y <= d:
                self.seen.setdefault(key, set()).add(n.tags.get("name") or "")
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
        # MOUNTAIN: (operator|ref, box, label); km by label.
        self.mountain, self.mountain_km = [], Counter()
        # PRIVATE: (ref, box, label); km left out by label.
        self.private, self.private_km = [], Counter()
        # Toll-rule countries: km of motorway tagged toll=no by operator|ref
        # and 0.05-degree cell, reported where the operator tolls elsewhere.
        self.untolled = Counter()
        # sections_only: the section ways by road, and the other ways of
        # those classes (road refs, class, [lon, lat] points), placed after.
        # sec_ckm: each section's km in OSM, one carriageway (a oneway way
        # counts half).
        self.sec_lines, self.pending, self.sec_ckm = {}, [], Counter()
        # myto (Czechia): the class I roads the law tolls; the map's
        # layers at each way's points (cz_myto.load); the ways sampled; the
        # ways the capture knows and doesn't, placed after; the end nodes of
        # tolled ways by class; tolled km (one carriageway) by class and
        # ref, and by class.
        self.law_refs, self.myto, self.samples, self.new_ways, self.mapped = set(), None, [], [], []
        self.myto_points = None
        self.tolled_nodes, self.ref_km, self.class_km = {"mw": {}, "nat": {}}, Counter(), Counter()
        # segments (Bulgaria): the main roads' ways, for the toll segments
        # to be found on (bgseg.Network), and whether each is a motorway.
        self.bg, self.bg_mw = None, []

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        hw = tags.get("highway", "")
        sec = self.sections.get(w.id)
        suffix = None
        if sec:
            c, f, road, edid = sec
            if self.rule.get("sections_only"):
                try:
                    pts = [(n.lon, n.lat) for n in w.nodes]
                    self.sec_lines.setdefault(road, []).append((LineString(pts), c, f, edid))
                    self.sec_ckm[edid] += cz_myto.length_m(pts) / 1000 * carriageway(tags)
                except (osmium.InvalidLocationError, ValueError):
                    pass
        else:
            # Czechia's toll map and Bulgaria's toll segments have class II
            # roads too (OpenStreetMap's secondary).
            if hw.endswith("_link") or hw not in ("motorway", "trunk", "primary") + (("secondary",) if self.rule.get("myto") or self.rule.get("segments") else ()):
                return
            c, f = classify(self.rule, tags), -1
            if self.bg is not None:
                return self.bg_way(w, c, tags)
            if c is None and self.rule.get("myto"):
                # Any main road: the toll map says whether, and in which
                # class, it is tolled.
                c = "nat"
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
        if self.rule.get("sections_only") and not sec:
            self.pending.append(([r.strip() for r in (tags.get("ref") or "").split(";") if r.strip()], c, coords, carriageway(tags)))
            return
        if self.rule.get("myto"):
            return self.myto_way(w, c, coords, tags)
        self.add(c, f, coords, tags, suffix)

    def bg_way(self, w, c, tags):
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return
        refs = {r.strip().replace("А", "A") for r in (tags.get("ref") or "").split(";") if r.strip()}
        roundabout = tags.get("junction") in ("roundabout", "circular")
        ow = tags.get("oneway")
        oneway = -1 if ow == "-1" else 0 if ow == "no" else 1 if ow in ("yes", "1", "true") or roundabout or tags.get("highway") == "motorway" else 0
        self.bg.add(refs, roundabout, oneway, [n.ref for n in w.nodes], coords, tags)
        # A motorway by its ref; or by its highway, but not a class I or II
        # road built as one (tolled only along its segments).
        self.bg_mw.append(any(re.match(r"^A\W?\d", r) for r in refs) or (c == "mw" and not any(re.fullmatch(r"\d{1,2}", r) for r in refs)))

    def myto_way(self, w, c, coords, tags):
        refs = [r.strip() for r in (tags.get("ref") or "").split(";") if r.strip()]
        ls = LineString(coords)
        self.samples.append((w.id, c, refs[0] if refs else "", ls))
        ends = (w.nodes[0].ref, w.nodes[-1].ref)
        nodes = [n.ref for n in w.nodes]
        if self.myto is not None:
            slots = self.myto_points.slots(w.id, ls)
            read = [i for i, l in enumerate(slots) if l != "unread"]
            if w.id not in self.myto and 2 * (len(slots) - len(read)) > len(slots) and all(i < cz_myto.END or i >= len(slots) - cz_myto.END for i in read):
                # A way added since, mostly unread and read (from its
                # neighbours' points) at most at its ends: placed by its
                # ends instead.
                self.new_ways.append((c, coords, tags, ends, nodes))
            else:
                n = len(slots)
                mids = [ls.interpolate((i + 0.5) / n, normalized=True) for i in range(n)]
                fl = [(l, (p.x, p.y)) for l, p in zip(slots, mids)]
                # Where the way is of the map layer's class itself (a
                # motorway, a class I road of the law), and so tolled
                # wherever the layer is drawn; another road the layer is
                # drawn on, only where it isn't beside one of those.
                hw = tags.get("highway")
                strong = {"mw": hw == "motorway" or any(re.match(r"^D\d", r) for r in refs), "nat": bool(set(refs) & self.law_refs)}
                self.mapped.append((fl, strong, ls, tags, refs, nodes))
            return
        # No capture: the law's roads by ref.
        parts = [(0.0, 1.0)] if tags.get("highway") != "secondary" and (c == "mw" or set(refs) & self.law_refs) else []
        self.add_parts(c, parts, ls, tags, refs, nodes)

    def add_parts(self, c, parts, ls, tags, refs, nodes):
        # The nodes on the tolled parts, with the ways' refs: where a way
        # added since may meet a tolled road.
        coords = list(ls.coords)
        if parts and len(nodes) == len(coords):
            # Along the line in degrees, as the parts are.
            run = [0.0]
            for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                run.append(run[-1] + math.hypot(x2 - x1, y2 - y1))
            total = run[-1] or 1
            for n, d in zip(nodes, run):
                if any(a - 1e-6 <= d / total <= b + 1e-6 for a, b in parts):
                    self.tolled_nodes[c].setdefault(n, set()).update(refs)
        for a, b in parts:
            piece = ls if (a, b) == (0, 1) else substring(ls, a, b, normalized=True)
            if piece.geom_type == "LineString" and len(piece.coords) >= 2:
                self.add_myto(c, list(piece.coords), tags, refs)

    def add_myto(self, c, coords, tags, refs):
        self.add(c, -1, coords, tags)
        km = cz_myto.length_m(coords) / 1000 * carriageway(tags)
        self.class_km[c] += km
        self.ref_km[(c, refs[0] if refs else "")] += km

    def add(self, c, f, coords, tags, suffix=None):
        ls = LineString(coords)
        if self.private and tags.get("toll") == "yes":
            refs = [r.strip() for r in (tags.get("ref") or "").split(";")]
            hit = [lab for ref, (a, b, x1, y1), lab in self.private if ref in refs and all(a <= x <= x1 and b <= y <= y1 for x, y in coords)]
            if hit:
                self.private_km[hit[0]] += ls.length * 111.32 * 0.6
                return
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
                    mtn = [lab for k, (a, b, x1, y1), lab in self.mountain if k == op and a <= piece.centroid.x <= x1 and b <= piece.centroid.y <= y1]
                    if op and suffix:
                        op = f"{op}|{suffix}"
                    elif mtn:
                        op = f"{op}|mountain"
                        self.mountain_km[mtn[0]] += piece.length * 111.32 * 0.68
                    elif op in self.split_at and (piece.centroid.y if self.split_at[op][2] else piece.centroid.x) > self.split_at[op][0]:
                        op = f"{op}|{self.split_at[op][1]}"
                    if op and op not in self.op_index:
                        self.op_index[op] = len(self.ops)
                        self.ops.append(op)
                    self.mwop.append(self.op_index.get(op, -1))
                    self.op_km[op] += piece.length * 111.32 * 0.68


def carriageway(tags):
    """The share of one carriageway a way is: a oneway way (a motorway's,
    a roundabout's) counts half."""
    ow = tags.get("oneway")
    one = ow in ("yes", "1", "true", "-1") or (ow != "no" and (tags.get("junction") in ("roundabout", "circular") or tags.get("highway") == "motorway"))
    return 0.5 if one else 1


def place_pending(h, cc, city=None):
    """Hungary: the ways outside the toll sections, placed. A section's
    other carriageway (within TWIN_M) takes the section's class and share.
    A chain of the others whose ends meet section ways fills a hole or gap
    in OSM's relations where annex 1 runs on there (but for holes of
    JOIN_KM) and the annex km the relations lack there leave room for it
    (one carriageway); it takes the section's class and share, the
    annex's sections' between (none: the two sections' mean share, the
    longer's class). A chain between two sections with nothing of the
    annex between them is a break, not tolled.
    The rest is left out on a road whose sections OSM has (COVERED of the
    annex's km, both carriageways of an M road), and on a road whose
    sections it lacks is tolled by its ref as before, but not inside
    Budapest (city) unless the road has a section there (the M0);
    reported by road."""
    kx = 111_320 * 0.68  # metres per degree of longitude near 47.2° N
    m = lambda pts: [(x * kx, y * 111_320) for x, y in pts]
    trees = {}
    for road, secs in h.sec_lines.items():
        geoms = [LineString(m(ls.coords)) for ls, *_ in secs]
        trees[road] = (STRtree(geoms), geoms, secs)
    # Annex 1's sections by road, in metres along it: its chainage
    # (km+m) orders them, but a km may run past 1000 m (204+2245), so a
    # section's length is its own ("m"), a stretch between sections the
    # chainage's (km x 1000 + m), and where the km went on, at least the
    # metres past its post (0+3134 to 1+565: 565).
    chain = lambda v: tuple(int(p) for p in v.split("+"))
    chain_m = lambda v: chain(v)[0] * 1000 + chain(v)[1]
    rows = json.load(open(os.path.join(os.path.dirname(__file__), "hu-annex1.json")))
    span, by_road, annex = {}, {}, Counter()
    for road in sorted({r["road"] for r in rows}):
        at, end = None, None
        for r in sorted((r for r in rows if r["road"] == road), key=lambda r: chain(r["start"])):
            if at is None:
                at = chain_m(r["start"])
            elif chain(r["start"]) != chain(end):
                at += max(0, chain_m(r["start"]) - chain_m(end), chain(r["start"])[1] if chain(r["start"])[0] > chain(end)[0] else 0)
            span[r["id"]] = (road, at, at + r["m"])
            by_road.setdefault(road, []).append((at, at + r["m"], r["f"], "mw" if r["level"] == "motorway" else "nat", r["id"]))
            annex[road] += r["m"] / 1000
            at, end = at + r["m"], r["end"]
    osm = Counter({road: sum(g.length for g in trees[road][1]) / 1000 for road in trees})
    # The km of a section its relation lacks (one carriageway).
    room = lambda e: max(0.0, (span[e][2] - span[e][1]) / 1000 - h.sec_ckm[e])
    covered = {road: osm[road] >= COVERED * km * (2 if road.startswith("M") else 1) for road, km in annex.items()}

    def between(a, b):
        """Annex 1 between sections a and b (in the order of the road):
        (km of its sections there, km between them, their class and
        suburban share by length, or None where there are none), or None."""
        (ra, a0, a1), (rb, b0, b1) = span[a], span[b]
        if ra != rb:
            return None
        lo, hi = (a1, b0) if a1 <= b0 else (b1, a0)
        inside = sorted((s0, s1, f, c, e) for s0, s1, f, c, e in by_road[ra] if s1 > lo and s0 < hi)
        there = [(min(s1, hi) - max(s0, lo), f, c) for s0, s1, f, c, _ in inside]
        on = sum(m for m, _, _ in there)
        by_class = Counter()
        for m, _, c in there:
            by_class[c] += m
        cf = (by_class.most_common(1)[0][0], sum(m * f for m, f, _ in there) / on) if on else None
        # The longest stretch there no section lists (a junction's, or a break).
        hole, at = 0, lo
        for s0, s1, *_ in inside:
            hole, at = max(hole, s0 - at), max(at, s1)
        # The km OSM's relations lack there: the unlisted metres and each
        # section's annex km beyond what its relation has.
        lack = (hi - lo - on) / 1000 + sum(room(e) for *_, e in inside)
        return on / 1000, (hi - lo) / 1000, cf, max(hole, hi - at) / 1000, lack

    def near(road, pt, d):
        """The nearest section way of road within d metres of pt, or None."""
        if road not in trees:
            return None
        tree, geoms, secs = trees[road]
        p = Point(pt)
        best = None
        for i in tree.query(p.buffer(d)):
            dist = geoms[i].distance(p)
            if dist <= d and (best is None or dist < best[0]):
                best = (dist, secs[i])
        return best and best[1]

    # Roads annex 1 tolls inside Budapest (the M0): a section way there.
    city_roads = {road for road, secs in h.sec_lines.items() if city is not None and any(ls.intersects(city) for ls, *_ in secs)}
    twins, gaps, breaks, dropped, kept, in_city = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    rest = []  # (refs, class, points, points in metres, carriageway share)
    for refs, c, coords, cw in h.pending:
        mc = m(coords)
        line = LineString(mc)
        n = max(2, int(line.length // 50) + 1)
        sample = [line.interpolate(i / (n - 1), normalized=True) for i in range(n)]
        hit = None
        for road in refs:
            ok = [near(road, (q.x, q.y), TWIN_M) for q in sample]
            if all(ok):
                hit = (road, ok[len(ok) // 2])
                break
        if hit:
            _, (_, sc, sf, _) = hit
            h.add(sc, sf, coords, {})
            twins[hit[0]] += line.length / 1000
        else:
            rest.append((refs, c, coords, mc, cw))
    # Chains of the remaining ways of one road: ways whose end comes within
    # BRIDGE_M of another (both carriageways, across a roundabout or a way
    # without the ref). A chain's ends are its two way ends farthest apart;
    # where each meets a section way of the road (within BRIDGE_M), the
    # chain is a gap in OSM's relations if annex 1 runs on between those
    # sections, a break (not tolled) if it has nothing between them, and
    # else is left as the road's other ways.
    decided = {}
    for road in sorted({r for refs, *_ in rest for r in refs}):
        ways = [i for i, w in enumerate(rest) if road in w[0] and i not in decided]
        if not ways:
            continue
        lines = [LineString(rest[i][3]) for i in ways]
        tree = STRtree(lines)
        seen = set()
        for k0 in range(len(ways)):
            if k0 in seen:
                continue
            chain, todo = set(), [k0]
            while todo:
                k = todo.pop()
                if k in chain:
                    continue
                chain.add(k)
                for p in (rest[ways[k]][3][0], rest[ways[k]][3][-1]):
                    q = Point(p)
                    todo += [int(j) for j in tree.query(q.buffer(BRIDGE_M)) if int(j) not in chain and lines[int(j)].distance(q) <= BRIDGE_M]
            seen |= chain
            km = sum(lines[k].length for k in chain) / 1000
            ckm = sum(lines[k].length * rest[ways[k]][4] for k in chain) / 1000  # one carriageway
            if km > 3 * GAP_KM and covered.get(road, False):
                continue  # long: not a gap; left out below
            pts = [p for k in chain for p in (rest[ways[k]][3][0], rest[ways[k]][3][-1])]
            a, b = max(((p, q) for i, p in enumerate(pts) for q in pts[i + 1:]), key=lambda pq: math.dist(*pq), default=(None, None))
            if a is None:
                continue
            ma, mb = near(road, a, BRIDGE_M), near(road, b, BRIDGE_M)
            ab = None
            if ma and mb and ma[3] != mb[3]:
                ab = between(*sorted((ma[3], mb[3]), key=lambda e: span[e][1]))

            def show(what, cf=None):
                if road in DEBUG_ROADS or "*" in DEBUG_ROADS:
                    ll = lambda p: f"{p[1] / 111_320:.5f},{p[0] / kx:.5f}"
                    print(cc, "chain", road, f"{km:.2f} km", len(chain), "ways, ends", ll(a), ma and ma[3], ll(b), mb and mb[3],
                          ab and f"annex {ab[0]:.2f} of {ab[1]:.2f} km between, hole {ab[3]:.3f}", "->", what, cf or "")

            if ma and mb and ma[3] == mb[3]:
                # A hole in one section's relation (or its other
                # carriageway, farther off): the km its relation lacks
                # leave room for the chain (a road beside a section OSM
                # has whole finds none).
                if ckm <= ROOM * room(ma[3]) + ROOM_KM:
                    for k in chain:
                        h.add(ma[1], ma[2], rest[ways[k]][2], {})
                        decided[ways[k]] = "gap"
                    gaps[road] += km
                    show("hole", ma[1:3])
                else:
                    show(f"left (room {room(ma[3]):.2f} km: annex {(span[ma[3]][2] - span[ma[3]][1]) / 1000:.2f}, OSM {h.sec_ckm[ma[3]]:.2f}; chain {ckm:.2f})")
                continue
            if ab is None:
                show("left (no section at an end)")
                continue
            on, gap, cf, hole, lack = ab
            if hole <= JOIN_KM and ckm <= ROOM * (lack + room(ma[3]) + room(mb[3])) + ROOM_KM:
                # The annex runs on between them (but for a junction's
                # few metres): OSM's relations lack it. Its km take the
                # class and share of the annex's sections there; where
                # there are none (the two sections meet in it, the annex
                # can't say where), their mean share, in the class of the
                # longer.
                longer = max((ma, mb), key=lambda s: (span[s[3]][2] - span[s[3]][1], span[s[3]][1]))
                sc, sf = cf or (longer[1], (ma[2] + mb[2]) / 2)
                for k in chain:
                    h.add(sc, sf, rest[ways[k]][2], {})
                    decided[ways[k]] = "gap"
                gaps[road] += km
                show("gap", (sc, round(sf, 3)))
            elif hole <= JOIN_KM:
                show(f"left (room {lack + room(ma[3]) + room(mb[3]):.2f} km)")
            elif on <= 0.001:
                # No annex section between them: not tolled.
                for k in chain:
                    decided[ways[k]] = "break"
                breaks[road] += km
                show("break")
            else:
                # Part of it is in the annex: left as the road's other ways.
                show("left (part in the annex)")
    for i, (refs, c, coords, mc, _) in enumerate(rest):
        if i in decided:
            continue
        road = next((r for r in refs if r in annex), refs[0] if refs else "(no ref)")
        km = LineString(mc).length / 1000
        if road in annex and not covered[road]:
            # OSM lacks this road's sections: tolled by its ref, outside Budapest.
            ls = LineString(coords)
            pieces = [ls]
            if city is not None and road not in city_roads and ls.intersects(city):
                out = ls.difference(city)
                pieces = [g for g in getattr(out, "geoms", [out]) if g.geom_type == "LineString" and not g.is_empty]
                in_city[road] += km * (1 - (out.length / ls.length if ls.length else 0))
            for g in pieces:
                if len(g.coords) >= 2:
                    h.add(c, -1, list(g.coords), {})
            kept[road] += km
        else:
            dropped[road] += km
    fmt = lambda c: {k: round(v, 1) for k, v in c.most_common()}
    print(cc, "other carriageways of toll sections (km):", fmt(twins))
    print(cc, "gaps in the sections' relations filled (km):", fmt(gaps))
    print(cc, "between sections annex 1 doesn't join, not tolled (km):", fmt(breaks))
    print(cc, "outside the sections of roads OSM has them for, not tolled (km):", fmt(dropped))
    print(cc, "roads whose sections OSM lacks, tolled by ref (km):", fmt(kept), "of which inside Budapest, not tolled:", fmt(in_city))
    print(cc, "totals: twins", round(sum(twins.values())), "gaps", round(sum(gaps.values())), "breaks", round(sum(breaks.values())),
          "left out", round(sum(dropped.values())), "by ref", round(sum(kept.values())), "in Budapest", round(sum(in_city.values())))
    for road, km in sorted(annex.items(), key=lambda kv: -kv[1]):
        if osm[road] or kept[road] or dropped[road]:
            print(cc, f"road {road}: annex {km:.1f} km, OSM sections {osm[road]:.1f} km{'' if covered[road] else ' (lacking)'}, twins {twins[road]:.1f}, gaps {gaps[road]:.1f}, "
                      f"breaks {breaks[road]:.1f}, left out {dropped[road]:.1f}, by ref {kept[road]:.1f}")


# Countries whose law lists its tolled sections: the list (from the law,
# by a parser beside it) found in OpenStreetMap by tools/roads/plnet.py.
# Poland: the e-TOLL regulation's annexes 1 (A and S, "mw") and 2 (other
# national roads, "nat"), from tools/roads/pl_network.py.
NETWORK = {"PL": "pl-network.json"}


# Czechia's tolled roads and sections, from the law (cz_network.py).
CZ_LAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cz-network.json")
# The km of ways OpenStreetMap changed since the toll map's reading (placed
# by their ends, or unread) the build accepts before it asks for a new
# reading.
CHANGED_KM = 25
# A point of a road where the map draws a layer of another class counts
# only if no point of a road of that class with the layer drawn is within
# about BESIDE_M (one cell either way: the old road beside a motorway).
BESIDE_M = 40


def myto_finish(h, cc, law, dst):
    """Czechia: the ways the capture doesn't know, the samples for the
    next capture beside dst, and the tolled km of each class against the
    law's.
    Returns what the tolled sections are, for the data's network."""
    # The points where a layer is drawn on a way of its class, in cells of
    # about BESIDE_M.
    cell = lambda x, y: (int(x * 111_320 * 0.65 // BESIDE_M), int(y * 111_320 // BESIDE_M))
    strong = {"mw": set(), "nat": set()}
    for fl, st, *_ in h.mapped:
        for l, (x, y) in fl:
            if l in st and st[l]:
                strong[l].add(cell(x, y))
    beside, unread = 0.0, 0.0
    for fl, st, ls, tags, refs, nodes in h.mapped:
        keep = []
        for l, (x, y) in fl:
            if l in st and not st[l]:
                cx, cy = cell(x, y)
                if any((cx + u, cy + v) in strong[l] for u in (-1, 0, 1) for v in (-1, 0, 1)):
                    l = None
                    beside += cz_myto.length_m(list(ls.coords)) / 1000 / len(fl)
            keep.append(l)
        c, parts = cz_myto.parts(keep, "nat")
        h.add_parts(c, parts, ls, tags, refs, nodes)
        unread += cz_myto.length_m(list(ls.coords)) / 1000 * sum(l == "unread" for l in cz_myto.filled(keep)) / len(keep)
    print(cc, f"km the map draws on other roads beside a road of its class (left out): {beside:.1f}")
    # Ways added since (mostly unread, read at most at their ends): those
    # of a ref, and
    # ref-less ones (a roundabout's) whose ends are on them or on tolled
    # ways of the ref, joined at their ends, are tolled in a class when
    # the chain has two ends or more (its ends, and the nodes where tolled
    # ways of the ref meet it) and every one is on a way of the ref (or a
    # ref-less one) tolled in that class.
    ways = h.new_ways
    refs_of = [[r.strip() for r in (t.get("ref") or "").split(";") if r.strip()] for _, _, t, _, _ in ways]
    # A node on a tolled way of ref r, or of a ref-less one.
    of_ref = lambda n, r: any(n in t and (r in t[n] or not t[n]) for t in h.tolled_nodes.values())
    # The ref-less ways in pieces joined at their ends.
    loose, seen = [], set()
    by_end = {}
    for i, rs in enumerate(refs_of):
        if not rs:
            for n in ways[i][3]:
                by_end.setdefault(n, []).append(i)
    for i, rs in enumerate(refs_of):
        if rs or i in seen:
            continue
        piece, todo = [], [i]
        seen.add(i)
        while todo:
            j = todo.pop()
            piece.append(j)
            for n in ways[j][3]:
                for k in by_end[n]:
                    if k not in seen:
                        seen.add(k)
                        todo.append(k)
        loose.append(piece)
    done, tolled_km = set(), 0.0
    # The refs to try: the new ways', and those of tolled ways a ref-less
    # one meets (at any of its nodes: a ring closes anywhere).
    for r in sorted({r for rs in refs_of for r in rs} | {r for t in h.tolled_nodes.values() for i, rs in enumerate(refs_of) if not rs for n in ways[i][4] for r in t.get(n, ())}):
        mine = [i for i, rs in enumerate(refs_of) if r in rs]
        ends_r = {n for i in mine for n in ways[i][3]}
        # Ref-less ways join as pieces (a roundabout's, perhaps split in
        # two) whose loose ends are on the ref's new ways or tolled ways:
        # at least one on a new way, unless they are all roundabout; a
        # closed ring, where the road enters and leaves it.
        group = list(mine)
        for piece in loose:
            out = [n for n, m in Counter(n for i in piece for n in ways[i][3]).items() if m == 1]
            ring = all(ways[i][2].get("junction") in ("roundabout", "circular") for i in piece)
            if out:
                ok = all(n in ends_r or of_ref(n, r) for n in out) and (ring or any(n in ends_r for n in out))
            else:
                # A closed ring (a roundabout): where the road enters and
                # leaves it, on two of its nodes or more, the ref's new
                # ways or tolled ways.
                ok = ring and len({n for i in piece for n in ways[i][4] if n in ends_r or of_ref(n, r)}) >= 2
            if ok:
                group += piece
        at = {}
        for i in group:
            for n in ways[i][4]:
                at.setdefault(n, []).append(i)
        seen = set()
        for i in group:
            if i in seen:
                continue
            chain, todo = [], [i]
            seen.add(i)
            while todo:
                j = todo.pop()
                chain.append(j)
                for n in ways[j][4]:
                    for k in at[n]:
                        if k not in seen:
                            seen.add(k)
                            todo.append(k)
            uses = Counter(n for j in chain for n in ways[j][3])
            inner = {n for j in chain for n in ways[j][4][1:-1]}
            ends = {n for n, m in uses.items() if m == 1 and n not in inner} | {n for j in chain for n in ways[j][4] if of_ref(n, r)}
            own = Counter(ways[j][0] for j in chain).most_common(1)[0][0]
            cls = next((k for k in (own, "nat" if own == "mw" else "mw")
                        if len(ends) >= 2 and all(n in h.tolled_nodes[k] and (r in h.tolled_nodes[k][n] or not h.tolled_nodes[k][n]) for n in ends)), None)
            if cls:
                for j in chain:
                    if j not in done:
                        done.add(j)
                        h.add_myto(cls, ways[j][1], ways[j][2], refs_of[j])
                        tolled_km += cz_myto.length_m(ways[j][1]) / 1000
    free_km = sum(cz_myto.length_m(ways[j][1]) / 1000 for j in range(len(ways)) if j not in done)
    if ways or unread:
        print(cc, f"ways unread (added since the reading): {len(ways)}, {tolled_km:.1f} km tolled (between tolled ways), {free_km:.1f} km not; {unread:.1f} km of other ways unread, not tolled")
    path = os.path.join(os.path.dirname(os.path.abspath(dst)), "cz-samples.json.gz")
    cz_myto.write_samples(h.samples, path, os.environ.get("OSM_EXTRACT", "")[:10] or None)
    print(cc, "samples for the next capture:", path, sum(cz_myto.count(list(ls.coords)) for *_, ls in h.samples), "points")
    if h.myto is not None and tolled_km + free_km + unread > CHANGED_KM:
        sys.exit(f"{cc}: {tolled_km + free_km + unread:.0f} km of ways changed since the toll map's reading, more than {CHANGED_KM}: take a new reading (tools/roads/cz_myto.py)")
    for (c, ref), v in sorted(h.ref_km.items(), key=lambda kv: -kv[1]):
        if v >= 0.5:
            print(cc, f"tolled {c:>3} {ref or '(no ref)':>6}: {v:6.1f} km")
    law_km = {c: sum(r["km"] for r in law["sections"] if r["class"] == c) for c in ("mw", "nat")}
    off = [c for c in law_km if abs(h.class_km[c] - law_km[c]) > 0.05 * law_km[c]]
    print(cc, "tolled km by class (one carriageway):", {c: round(h.class_km[c], 1) for c in law_km}, "law:", {c: round(v, 1) for c, v in law_km.items()})
    if h.myto is not None:
        for cls, lon, lat, px in json.load(open(cz_myto.CAPTURE, encoding="utf-8")).get("unmatched", []):
            print(cc, f"the map draws {cls} away from the sampled ways near {lat},{lon} ({px} pixels)")
        if off:
            sys.exit(f"{cc}: tolled km of {', '.join(off)} more than 5% off the law's")
    cap = json.load(open(cz_myto.CAPTURE, encoding="utf-8")) if h.myto is not None else {}
    return law["source"].split(":")[0] + (f"; tolled stretches as the toll operator's map draws them ({cap['url']}, read {cap['date']})" if cap else "")


def bg_finish(h, cc, doc):
    """Bulgaria: the class I and II roads' toll segments placed on the
    main roads (bgseg.py); the parts of ways they cover are tolled class I
    and II roads, a motorway's other parts motorway. Returns what the
    tolled roads are, for the data's network."""
    net = h.bg
    rows = [r for r in doc["segments_2022"]["rows"] if r[0] in ("I", "II")]
    placed, wanted, missed = Counter(), Counter(), Counter()
    anyroad = 0
    for cls, road, no, lat1, lon1, lat2, lon2, m in rows:
        wanted[road] += m / 1000
        got = net.place((lon1, lat1), (lon2, lat2), m, road)
        if got is None:
            got = net.place((lon1, lat1), (lon2, lat2), m, None)
            anyroad += got is not None
        if got is None:
            missed[road] += m / 1000
        else:
            placed[road] += m / 1000
    for road in sorted(wanted, key=int):
        print(cc, f"road {road:>2}: {placed[road]:6.1f} of {wanted[road]:6.1f} segment km placed" + (f", {missed[road]:.1f} not" if missed[road] else ""))
    listed = set(doc["roads"]["I"]) | set(doc["roads"]["II"])
    for road in sorted(listed ^ set(wanted), key=int):
        print(f"::warning::{cc}: road {road} is in " + ("the list of 2025 but has no segments of 2022" if road in listed else "the segments of 2022 but not the list of 2025"))
    total, lost = sum(wanted.values()), sum(missed.values())
    print(cc, f"segments placed: {total - lost:.0f} of {total:.0f} km; {anyroad} on roads of another ref")
    for w in range(len(net.ways)):
        tags = net.ways[w][6]
        for run in net.covered(w):
            h.add("nat", -1, run, tags)
        if h.bg_mw[w]:
            for run in net.uncovered(w):
                h.add("mw", -1, run, tags)
    if lost > 0.02 * total:
        sys.exit(f"{cc}: {lost:.0f} of {total:.0f} segment km not found in OpenStreetMap")
    return (doc["source"].split(":")[0] + "; the motorways by their ref or tag, the class I and II roads by the toll segments of "
            + doc["segments_2022"]["source"].split(":")[0] + " (the settlements left out)")


def encode(lines):
    out = []
    for run in lines:
        s = LineString(run).simplify(SIMPLIFY_M / 111_320, preserve_topology=False)
        pts = [[round(x * 1e5), round(y * 1e5)] for x, y in s.coords]
        if len(pts) >= 2:
            out.append([v for p in pts for v in p])
    return out


def main_network(cc, src, dst):
    import plnet
    here = os.path.dirname(os.path.abspath(__file__))
    doc = json.load(open(os.path.join(here, NETWORK[cc]), encoding="utf-8"))
    lines, report = plnet.build(src, doc["sections"])
    total = Counter()
    for (text, km, why), s in zip(report, doc["sections"]):
        print(cc, "section", f"{km:7.1f} km" if km is not None else "NOT FOUND ", text, why)
        total[s["class"]] += km or 0
    print(cc, "km by class (one carriageway):", {k: round(v) for k, v in total.items()})
    bad = [r for r in report if r[1] is None]
    if bad:
        sys.exit(f"{cc}: {len(bad)} of {len(report)} sections not found in OpenStreetMap")
    out = {"country": cc, "simplify_m": SIMPLIFY_M, "mw": encode(lines["mw"]), "nat": encode(lines["nat"]), "network": doc["source"]}
    if os.environ.get("OSM_EXTRACT"):
        out["osm_extract"] = os.environ["OSM_EXTRACT"][:10]
    if FREE.get(cc):
        out["left_out"] = sorted({f[-1] for f in FREE[cc]})
    with gzip.open(dst, "wt", encoding="utf-8") as fo:
        json.dump(out, fo, separators=(",", ":"))
    print(cc, {k: len(v) for k, v in out.items() if k in ("mw", "nat")})


def main(cc, src, dst, areas=None):
    if cc in NETWORK:
        return main_network(cc, src, dst)
    rule = RULES[cc]
    urban = city = None
    if areas and cc == "HU":
        # Budapest's boundary: annex 1 lists none of the city's roads.
        b = Boundary("Budapest")
        b.apply_file(areas, locations=True)
        if not b.parts:
            sys.exit("HU: Budapest's administrative boundary not found")
        city = unary_union(b.parts)
        print(cc, "Budapest's boundary:", len(b.parts), "polygons")
    elif areas:
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
                sys.exit(f"{cc}: junction {name!r} not found (split of {key}); junctions in the box: {sorted(j.seen.get(key, []))}")
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
                    sys.exit(f"{cc}: junction {name!r} not found (end of {label}); junctions in the box: {sorted(j.seen.get(f'{ref}|{i}', []))}")
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
    law = None
    if rule.get("myto"):
        law = json.load(open(CZ_LAW, encoding="utf-8"))
        h.law_refs = {r["ref"] for r in law["sections"] if r["class"] == "nat"}
        h.myto = cz_myto.load()
        h.myto_points = cz_myto.Points(h.myto) if h.myto is not None else None
        if h.myto is None:
            print(f"::warning::{cc}: no capture of the toll map: every way of the law's roads counted")
    bg = None
    if rule.get("segments"):
        bg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), rule["segments"]), encoding="utf-8"))
        h.bg = bgseg.Network()
    h.tolled = list(TOLLED.get(cc, []))
    h.untolled_boxes = list(UNTOLLED.get(cc, []))
    h.mountain = list(MOUNTAIN.get(cc, []))
    h.private = list(PRIVATE.get(cc, []))
    h.apply_file(src, locations=True)
    if rule.get("sections_only"):
        place_pending(h, cc, city)
    if law:
        network = myto_finish(h, cc, law, dst)
    if bg:
        network = bg_finish(h, cc, bg)
    if cc == "HU":
        network = ("25/2013. (V. 31.) NFM rendelet, 1. melléklet: its toll sections by OpenStreetMap's relations tagged ref:HU:edid"
                   " (where OpenStreetMap mostly lacks a road's, its ways by their ref; not inside Budapest but the M0)")
    tolling = {op.split("|")[0] for op in h.op_km}
    for (key, x, y), km in sorted(h.untolled.items(), key=lambda kv: -kv[1]):
        if km >= 1 and key.split("|")[0] in tolling:
            print(cc, "motorway tagged toll=no of a tolling operator:", key, f"near {y:.2f},{x:.2f}", round(km, 1), "km")
    for key, box, label, suffix in h.tolled:
        if not h.tolled_km[label]:
            sys.exit(f"{cc}: no toll=no ways of {key} in {box} ({label})")
        print(cc, "counted as toll motorway (both carriageways):", label, round(h.tolled_km[label], 1), "km")
    for key, box, label in h.mountain:
        if not h.mountain_km[label]:
            sys.exit(f"{cc}: no ways of {key} in {box} ({label})")
        print(cc, "mountain stretch (both carriageways):", label, round(h.mountain_km[label], 1), "km")
    for key, box, label in h.untolled_boxes:
        print(cc, "left out as free before a barrier (both carriageways):", label, round(h.untolled_km[label], 1), "km")
    for label, km in h.free_km.items():
        print(cc, "left out km (both carriageways):", label, round(km))
    for ref, box, label in h.private:
        # Not an error: OSM may not tag the tunnel toll=yes; its km then
        # count as tolled road too.
        print(cc, "left out as privately tolled (both carriageways):", label, round(h.private_km[label], 1), "km")
    if urban is not None:
        print(cc, "national road km left out inside municipalities (both carriageways):", round(h.urban_km))
    out = {"country": cc, "simplify_m": SIMPLIFY_M, "mw": h.lines["mw"], "nat": h.lines["nat"]}
    if law or bg or cc == "HU":
        out["network"] = network
    # The extract's date (the workflow passes its osmosis_replication_timestamp).
    if os.environ.get("OSM_EXTRACT"):
        out["osm_extract"] = os.environ["OSM_EXTRACT"][:10]
    if sections:
        out["mwf"], out["natf"] = h.shares["mw"], h.shares["nat"]
    if h.free or h.private_km:
        # The stretches left out, by name: the tool says the km it counts
        # as local roads include them.
        out["left_out"] = sorted({label for *_, label in h.free} | {label for label, km in h.private_km.items() if km > 0})
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
