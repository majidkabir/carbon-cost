"""Builds the AP-68 Bilbao–Zaragoza (Avasa) toll table from the Ministry of
Transport's tolls in force (fetch.py's es-min-ap68-<year>.txt) and OSM
(es-ap68-links-osm.json): a closed system by entry and exit.

Usage: python3 es_ap68.py fetched/ out-dir -> out-dir/es-ap68-<year>-01-01.json

Prices: the "Tarifa general" pairs (either way: "recorridos directos e
inversos"), Pesados 1 and 2, excluding 21% IVA. With a tag ("sistema
dinámico", `etc`): the tables of Haro–Alfaro (Real Decreto 584/2014, 50%
on internal trips; Cenicero–Agoncillo free) and Zambrana–Tudela (Pesados 2,
the convenio of Real Decreto 757/2019), whichever is lower. Heavy vehicles
between Ziorraga and Altube are exempt (the Diputación Foral de Álava's
convenio). Bilbao service area – Arrigorriaga-Bilbao, a ramp of its own,
is left out.

Stations: each placed at the junction whose exit link is signposted to it
(OSM's destination tags), in the tariff's order (es_stretch.assign); the
system's stations are the carriageways' stretches between consecutive
entries/exits (es_stretch.stretches). The motorway's ends (Bilbao,
Zaragoza) are its carriageways' ends.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import es_stretch, m6toll  # noqa: E402

VAT = 1.21
ORDER = ["BILBAO", "ARRIGORRIAGA", "ARETA", "LLODIO", "ZIORRAGA", "ALTUBE", "SUBIJANA", "AUTOP.BURGOS", "ZAMBRANA", "HARO",
         "CENICERO", "FUENMAYOR", "LOGROÑO", "RECAJO", "AGONCILLO", "LODOSA", "CALAHORRA", "ALFARO", "AUTOP.NAVARRA", "TUDELA",
         "GALLUR", "ALAGÓN pk 272", "ALAGÓN pk 275", "ZARAGOZA"]
ALIAS = {"FUENMAYOR-NAVARRETE": "FUENMAYOR"}
# Words a station's exit is signposted with (lower case, accents dropped).
SIGN = {"AUTOP.BURGOS": ["ap 1", "burgos"], "AUTOP.NAVARRA": ["ap 15", "pamplona", "iruna"], "FUENMAYOR": ["fuenmayor", "navarrete"],
        "ALAGÓN pk 272": ["alagon"], "ALAGÓN pk 275": ["alagon"], "LOGROÑO": ["logrono"], "ARETA": ["areta", "amurrio"]}
LABEL = {"AUTOP.BURGOS": "AP-1 (Burgos)", "AUTOP.NAVARRA": "AP-15 (Navarra)", "ALAGÓN pk 272": "Alagón (pk 272)", "ALAGÓN pk 275": "Alagón (pk 275)"}


def label(s):
    return LABEL.get(s, s.title().replace("ñ", "ñ"))


def tables(text):
    """{"G": {(a, b): (p1, p2)}, "HA": ..., "ZT": {(a, b): (None, p2)}}, prices with IVA."""
    out, sec = {}, None
    for line in text.splitlines():
        if "TARIFA GENERAL" in line:
            sec = "G"
        elif "TRAMO HARO-ALFARO TRAS" in line:
            sec = "HA"
        elif "ZAMBRANA-TUDELA CON DESCUENTOS" in line:
            sec = "ZT"
        m = re.match(r"^(\S.*?)\s{2,}(\S.*?)\s{2,}(\d+,\d\d)(?:\s+(\d+,\d\d)\s+(\d+,\d\d))?\s*$", line)
        if m and sec:
            a, b = (ALIAS.get(x.strip(), x.strip()) for x in m.group(1, 2))
            v = [float(x.replace(",", ".")) for x in m.groups()[2:] if x]
            out.setdefault(sec, {})[(a, b)] = (v[1], v[2]) if len(v) == 3 else (None, v[0])
    return out


def main(fetched, out, year="2026"):
    text = open(os.path.join(fetched, f"es-min-ap68-{year}.txt"), encoding="utf-8").read()
    t = tables(text)
    if len(t.get("G", {})) < 200 or len(t.get("HA", {})) < 30 or len(t.get("ZT", {})) < 150:
        sys exit = None
    for need in ("ZIORRAGA-ALTUBE", "quedarán exentos", "Real Decreto 584/2014", "Real Decreto 757/2019", "bonificación del 75%"):
        if need not in re.sub(r"\s+", " ", text):
            sys.exit(f"AP-68: the Ministry's notes no longer say {need!r}")
    names = {x for k in t["G"] for x in k} - {"BILBAO-A.SERV.", "ARRIG.-BILBAO"}
    if names != set(ORDER):
        sys.exit(f"AP-68: stations changed: {sorted(names ^ set(ORDER))}")

    def price(a, b, tb, g):
        v = tb.get((a, b)) or tb.get((b, a))
        return v and v[g]

    osm = json.load(open(os.path.join(fetched, "es-ap68-links-osm.json")))
    ls = es_stretch.lines(osm, ["AP-68"])
    juncs = es_stretch.signs(osm)
    keys = {s: SIGN.get(s, [es_stretch.plain(s)]) for s in ORDER}
    match = lambda s, words: any(re.search(r"\b" + k + r"\b", words) for k in keys[s])
    pts = {}
    for line in ls:
        cum = m6toll.along(line)
        got = es_stretch.assign(ORDER[1:-1], match, line, cum, juncs)
        for s, x in got.items():
            pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
    # The ends: the carriageways' ends nearest Bilbao and Zaragoza.
    ...
