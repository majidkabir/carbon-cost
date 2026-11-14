"""Builds an ESTIMATE of Italy's motorway tolls (it-<date>.json) from
Autostrade per l'Italia's unit rates (fetch.py's it-aspi-tariffe.html)
and the other concessions' unit rates for 2025 as their sheets published
by the Ministry (MIT) state them (transcribed/it-mit-*.json).

Usage: python3 it.py transcribed/ fetched/ out-dir -> out-dir/it-<date>.json

Italian motorway tolls are each concession's unit rate per km (by class
and by plain or mountain stretch) times the km between the toll
stations, plus VAT, rounded to 10 cents. No station-to-station table can
be fetched, so the table prices the route's km on toll motorways
(OpenStreetMap ways tagged toll=yes, roads/data/it.json.gz) at Autostrade
per l'Italia's plain-stretch rate, VAT included: class B (two axles over
1.30 m), 3, 4 and 5 (five or more axles). That is an estimate: mountain
stretches cost about 18% more on ASPI's network, other concessions have
their own rates (mostly higher), and the per-trip rounding and the
concessions' fixed-toll stretches (open system) aren't modelled.
"""
import html, json, os, re, sys

# The concessions' ways as OpenStreetMap tags them (operator, and ref where
# one operator's motorways differ), the sheet and its stretch that prices
# them. Ways of other operators, and of those with no sheet with rates
# (Autostrade per l'Italia, Consorzio per le Autostrade Siciliane,
# Superstrada Pedemontana Veneta, Salerno Pompei Napoli, Tangenziale di
# Napoli, Ivrea Torino Piacenza's A5, A4/A5 and A55), take ASPI's rate.
OPS = [
    ("Autostrada del Brennero S.p.A.", "", "a22-brennero", ""),
    ("Autostrada Asti-Cuneo S.p.A.", "", "asti-cuneo", ""),
    ("Autostrada dei Fiori S.p.A.", "", "autostrada-dei-fiori-a6", ""),
    ("Società Autostrade Alto Adriatico S.p.A.", "", "autostrade-alto-adriatico", ""),
    ("Autovia Padana S.p.A.", "", "autovia-padana", ""),
    ("Società di Progetto Brebemi S.p.A", "", "brebe-mi", ""),
    ("Autostrada Brescia Verona Vicenza Padova S.p.A.", "", "brescia-padova", ""),
    ("CAV S.p.A.", "", "cav", ""),
    ("Concessioni del Tirreno S.p.A.", "A10", "cdt-a10", "A10"),
    ("Concessioni del Tirreno S.p.A.", "", "cdt-a10", "A12"),
    ("Milano Serravalle - Milano Tangenziali S.p.A.", "A7", "mi-serravalle-mi-tangenziali", ""),
    ("Autostrada Pedemontana Lombarda S.p.A .", "A36", "pedemontana-lombarda", "A36-A"),
    ("Autostrada Pedemontana Lombarda S.p.A .", "A59", "pedemontana-lombarda", "A59"),
    ("Autostrada Pedemontana Lombarda S.p.A .", "A60", "pedemontana-lombarda", "A60"),
    ("RAV Raccordo Autostradale Valle d'Aosta S.p.A.", "", "rav", ""),
    ("Società Autostrada Ligure Toscana p.a.", "A15", "salt-a15", ""),
    ("SAT p.A.", "", "sat", ""),
    ("SATAP S.p.A.", "A4", "satap-a4", "A4"),
    ("Ivrea Torino Piacenza S.p.A.", "A21", "satap-a4", "A21"),
    ("Società Autostrade Valdostane S.p.A.", "", "sav", ""),
    ("SITAF S.p.A.", "A32", "sitaf", ""),
    ("Strada dei Parchi S.p.A.", "", "strada-dei-parchi", ""),
    ("Tangenziale Esterna S.p.A.", "", "tangenziale-esterna", ""),
]
AXLES = [(2, 2, "B"), (3, 3, "3"), (4, 4, "4"), (5, 0, "5")]
# Pedemontana Lombarda's free-flow classes: 3 trucks, 4 articulated or
# with trailer.
PEDEMONTANA = {"B": "3", "3": "3", "4": "4", "5": "4"}
VAT = 1.22


def operator_rows(transcribed):
    rows, used = [], {}
    for op, ref, sheet, stretch in OPS:
        d = json.load(open(os.path.join(transcribed, f"it-mit-{sheet}.json"), encoding="utf-8"))
        used[sheet] = d
        key = f"{op}|{ref}" if ref else op
        for lo, hi, cl in AXLES:
            if sheet == "pedemontana-lombarda":
                r = d["rates"][PEDEMONTANA[cl]]
                unit, anas = r[stretch], r["anas"]
            else:
                r = d["rates"][stretch] if stretch else d["rates"]
                unit, anas = r[cl]["unit"], r[cl]["anas"] or 0
            row = {"component": "toll", "road": "motorway", "operator": key, "min_kg": 3501, "min_axles": lo, "rate": round((unit + anas) * VAT, 5)}
            if hi:
                row["max_axles"] = hi
            if lo == 2:
                del row["min_axles"]
            rows.append(row)
    return rows, used

MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
          "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}


def main(transcribed, fetched, out):
    p = os.path.join(fetched, "it-aspi-tariffe.html")
    t = open(p, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).replace("\xa0", " ")
    num = r"(\d,\d{5})"
    plain = re.search(r"Tariffa di pianura €/Km " + " ".join([num] * 5), t)
    mountain = re.search(r"Tariffa di montagna €/Km " + " ".join([num] * 5), t)
    upd = re.search(r"comprensive dell.IVA ?\(22%\) aggiornate al (\d+)° (\w+) (\d{4})", t)
    if not plain or not mountain or not upd:
        sys.exit("it-aspi-tariffe: unit rates or their date not found")
    if not re.search(r"CLASSI DI VEICOLO A B 3 4 5", t):
        sys.exit("it-aspi-tariffe: class header not found")
    valid_from = f"{upd.group(3)}-{MONTHS[upd.group(2)]:02d}-{int(upd.group(1)):02d}"
    pl = [float(v.replace(",", ".")) for v in plain.groups()]
    mo = [float(v.replace(",", ".")) for v in mountain.groups()]
    rows = [
        {"component": "toll", "road": "motorway", "min_kg": 3501, "max_axles": 2, "rate": pl[1]},
        {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": pl[2]},
        {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 4, "max_axles": 4, "rate": pl[3]},
        {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 5, "rate": pl[4]},
    ]
    up = round(100 * (mo[4] / pl[4] - 1))
    ops, used = operator_rows(transcribed)
    rows += ops
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": valid_from, "valid_to": f"{valid_from[:4]}-12-31",
        "name": "Italian motorway tolls (ESTIMATE: each concession's unit rate per km)",
        "law": "Estimate. Italian motorway tolls are each concession's unit rate per km, by vehicle class (A, B by height for two axles; 3, 4, 5 by axles) and by plain or mountain stretch, plus the ANAS surcharge (law 102/2009 art. 19 c. 9-bis), times the km between toll stations, plus 22% VAT, rounded to 10 cents (the concession agreements with the Ministry, under the State's laws and CIPE resolutions). "
               "No station-to-station table can be fetched, so the route's km on toll motorways (OpenStreetMap ways tagged toll=yes) are priced by the operator OpenStreetMap gives the ways: "
               f"the concessions with a published sheet at their unit rate for 2025, ANAS surcharge and VAT included, as their sheets sent to the Ministry of Infrastructure and Transport (Directive (EU) 2022/362 art. 11, published March 2025) state them (the 2026 change, 1.5% on most networks, isn't applied: the Ministry's note couldn't be found), each concession's plain-stretch rate unless it has only mountain stretches; "
               f"Autostrade per l'Italia's network and the concessions without rates in their sheet at Autostrade per l'Italia's plain-stretch unit rate, VAT included, in force from {valid_from}: class B {pl[1]:.5f}, 3 {pl[2]:.5f}, 4 {pl[3]:.5f}, 5 {pl[4]:.5f} euro per km. "
               f"Pedemontana Lombarda's classes are its own (3 trucks up to three axles, 4 articulated or with trailer). Mountain stretches cost about {up}% more on ASPI's network (class 5 {mo[4]:.5f}), some concessions price parts of their network higher (SATAP's A4 Novara Est-Milano, CAV's Passante di Mestre, SITAF's Salbertrand), Milan's ring roads and other open-system stretches charge fixed tolls, and the rounding isn't modelled, so the true toll can differ.",
        "sources": [{"title": "Autostrade per l'Italia: come si calcola il pedaggio (unit rates per km, VAT included)", "url": "https://www.autostrade.it/it/servizi-al-cliente/pedaggio/come-si-calcola-il-pedaggio"}]
        + [{"title": f"MIT: {d['operator']}, tariff sheet (Directive (EU) 2022/362 art. 11), p. {d['source']['page']}", "url": d["source"]["url"]} for d in used.values()],
        "vehicles": "Vehicles by class: two axles over 1.30 m at the front axle (class B), three, four, five or more axles (classes 3, 4, 5); the tool prices trucks over 3.5 t",
        "min_kg": 3501,
        "tolled_roads": "The toll motorways (autostrade a pedaggio) of all concessions, as OpenStreetMap tags them (toll=yes); not the toll-free ones (A2, A19, A29, ring roads) nor the Alpine tunnels, which have their own tables.",
        "motorway_share": 1,
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"it-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, pl, mo)


if __name__ == "__main__":
    main(*sys.argv[1:])
