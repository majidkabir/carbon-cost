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
    flat = re.sub(r"\s+", " ", text)
    t = tables(text)
    if len(t.get("G", {})) < 200 or len(t.get("HA", {})) < 30 or len(t.get("ZT", {})) < 150:
        sys.exit(f"AP-68: tables of {[(k, len(v)) for k, v in t.items()]} pairs")
    for need in ("RECORRIDO ZIORRAGA-ALTUBE", "los vehículos pesados que utilicen el tramo Ziorroga-Altube, con entrada y salida por los enlaces del mismo nombre, quedarán exentos",
                 "Real Decreto 584/2014", "Real Decreto 757/2019", "los vehículos pesados 2 que realicen recorridos internos en el tramo Zambrana-Tudela disfrutarán de una bonificación del 75%",
                 "cuando se abone el peaje con el sistema dinámico"):
        if need not in flat:
            sys.exit(f"AP-68: the Ministry's notes no longer say {need!r}")
    names = {x for k in t["G"] for x in k} - {"BILBAO-A.SERV.", "ARRIG.-BILBAO"}
    if names != set(ORDER):
        sys.exit(f"AP-68: stations changed: {sorted(names ^ set(ORDER))}")

    osm = json.load(open(os.path.join(fetched, "es-ap68-links-osm.json")))
    stamp = osm.get("osm3s", {}).get("timestamp_osm_base", "")[:10]
    ls = es_stretch.lines(osm, ["AP-68"])
    juncs = es_stretch.signs(osm)
    keys = {s: SIGN.get(s, [es_stretch.plain(s)]) for s in ORDER}
    match = lambda s, w: any(re.search(r"\b" + k + r"\b", w) for k in keys[s])
    pts, filled = {}, set()
    for line in ls:
        cum = m6toll.along(line)
        if cum[-1] < 20:
            continue
        got, seq = es_stretch.assign(ORDER[1:-1], match, line, cum, juncs)
        if len(got) < 5:
            continue
        seq = [ORDER[0]] + seq + [ORDER[-1]] if seq[0] == ORDER[1] else [ORDER[-1]] + seq + [ORDER[0]]
        # The motorway's ends: Bilbao and Zaragoza where the carriageway ends.
        if es_stretch.open_end(line[0], m6toll.at(line, cum, 0)[1], ls, line):
            got[seq[0]] = 0.0
        if es_stretch.open_end(line[-1], m6toll.at(line, cum, cum[-1])[1], ls, line):
            got[seq[-1]] = cum[-1]
        filled |= set(es_stretch.fill(seq, got, line, cum, juncs))
        for s, x in got.items():
            pts.setdefault(s, []).append(m6toll.at(line, cum, x)[0])
    miss = [s for s in ORDER if s not in pts]
    secs = es_stretch.stretches(ls, pts)

    def find(tb, a, b):
        v = tb.get((a, b)) or tb.get((b, a))
        return v

    exempt = {("ZIORRAGA", "ALTUBE"), ("ALTUBE", "ZIORRAGA")}

    def cash(a, b):
        if (a, b) in exempt:
            return {"P1": 0.0, "P2": 0.0}
        v = find(t["G"], a, b)
        return v and {"P1": round(v[0] / VAT, 4), "P2": round(v[1] / VAT, 4)}

    def tag(a, b):
        c = cash(a, b)
        if not c:
            return None
        out = dict(c)
        ha, zt = find(t.get("HA", {}), a, b), find(t.get("ZT", {}), a, b)
        if ha:
            out = {"P1": min(out["P1"], round(ha[0] / VAT, 4)), "P2": min(out["P2"], round(ha[1] / VAT, 4))}
        if zt:
            out["P2"] = min(out["P2"], round(zt[1] / VAT, 4))
        return out if out != c else None

    groups = [{"name": "P2", "min_kg": 3501, "min_axles": 4}, {"name": "P1", "min_kg": 3501}]
    cs = es_stretch.system("AP-68", "The Ministry of Transport's tolls in force: by entry and exit, either way; with a tag, the Haro–Alfaro and Zambrana–Tudela tables.", secs, cash, groups, label)
    cs["etc_prices"] = es_stretch.system("AP-68", "", secs, tag, groups, label)["prices"]
    g = t["G"][("BILBAO", "ZARAGOZA")]
    tb = {
        "country": "ES", "currency": "EUR", "valid_from": f"{year}-01-01", "crossings": True, "osm_extract": stamp,
        "name": "AP-68 Bilbao – Zaragoza (Avasa)",
        "law": (f"The Ministry of Transport's tolls in force from 1 January {year} on the AP-68: by entry and exit, either way, Pesados 1 (two or three axles) and Pesados 2 (four or more; "
                f"Bilbao – Zaragoza EUR {g[1]:.2f} with IVA), excluding 21% IVA. Heavy vehicles between Ziorraga and Altube are exempt (the Diputación Foral de Álava's convenio). "
                "Paying by tag (sistema dinámico, `etc`): the Haro–Alfaro tolls after Real Decreto 584/2014's 50% (Cenicero–Agoncillo free) and the Zambrana–Tudela Pesados 2 tolls "
                "after Real Decreto 757/2019's 75%, where lower. Stations: each carriageway's stretch between two consecutive entries/exits, at the OpenStreetMap junctions whose exits are "
                "signposted to them in the table's order"
                + (f", {', '.join(label(s) for s in sorted(filled, key=ORDER.index))} by elimination (the only numbered junction between their neighbours)" if filled else "")
                + ", Bilbao and Zaragoza at the motorway's ends"
                + (f"; not placed: {', '.join(label(s) for s in miss)}" if miss else "") + ". Bilbao's service area – Arrigorriaga-Bilbao ramp isn't built."),
        "sources": [{"title": f"Ministerio de Transportes: peajes vigentes AP-68 {year}", "url": f"https://cdn.transportes.gob.es/portal-web-transportes/carreteras/nuestrared/autopistaspeaje/peajes-actuales/autopista-ap-68,-bilbao---zaragoza-{year}.pdf"},
                    {"title": "OpenStreetMap (Overpass API): AP-68 carriageways, junctions and signposted links", "url": "https://www.openstreetmap.org/"}],
        "vehicles": "Pesados 1: trucks of two or three axles; Pesados 2: four axles or more", "min_kg": 3501,
        "tolled_roads": "AP-68 from Bilbao to Zaragoza.",
        "closed_systems": [cs], "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"es-ap68-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, f"{len(ORDER) - len(miss)}/{len(ORDER)} placed (by elimination: {sorted(filled)}),", len(secs), "stretches,", len(cs["prices"]), "pairs,", len(cs["etc_prices"]), "tag pairs" + (f"; unplaced {miss}" if miss else ""))


if __name__ == "__main__":
    main(*sys.argv[1:])
