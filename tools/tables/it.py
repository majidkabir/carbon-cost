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
# Napoli), take ASPI's rate; Ivrea Torino Piacenza's A5, A4/A5 and A55
# only where its page (PAGES) gives the rates.
OPS = [
    ("Autostrada del Brennero S.p.A.", "", "a22-brennero", ""),
    ("Autostrada Asti-Cuneo S.p.A.", "", "asti-cuneo", ""),
    ("Ivrea Torino Piacenza S.p.A.", "", "", ""),
    ("Autostrada dei Fiori S.p.A.", "", "autostrada-dei-fiori-a6", ""),
    ("Società Autostrade Alto Adriatico S.p.A.", "", "autostrade-alto-adriatico", ""),
    ("Autovia Padana S.p.A.", "", "autovia-padana", ""),
    ("Società di Progetto Brebemi S.p.A", "", "brebe-mi", ""),
    ("Autostrada Brescia Verona Vicenza Padova S.p.A.", "", "brescia-padova", ""),
    ("CAV S.p.A.", "", "cav", "A4"),
    ("CAV S.p.A.", "A57", "cav", "A57"),
    ("CAV S.p.A.", "A4|Passante", "cav", "Passante"),
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
    ("SATAP S.p.A.", "A4|Novara Est-Milano", "satap-a4", "A4 Novara Est-Milano"),
    ("Ivrea Torino Piacenza S.p.A.", "A21", "satap-a4", "A21"),
    ("Società Autostrade Valdostane S.p.A.", "", "sav", ""),
    ("SITAF S.p.A.", "A32", "sitaf", ""),
    ("Strada dei Parchi S.p.A.", "", "strada-dei-parchi", ""),
    ("Tangenziale Esterna S.p.A.", "", "tangenziale-esterna", ""),
]
# The concessions whose own pages give their unit rates for users (VAT and
# the ANAS fee included) for the year: fetch.py's file, the row's label
# (a regex) and the operator keys it prices. Where a page's rates are of
# the table's year they replace the 2025 sheet's.
PAGES = [
    ("it-satap-a4", r"TARIFF A\b", ["SATAP S.p.A.|A4"]),
    ("it-satap-a4", r"TARIFF B\b", ["SATAP S.p.A.|A4|Novara Est-Milano"]),
    ("it-itp-a21", r"Plain tariff", ["Ivrea Torino Piacenza S.p.A.|A21"]),
    ("it-itp-a5", r"Plain tariff", ["Ivrea Torino Piacenza S.p.A."]),
    ("it-asti-cuneo", r"RATE B \(mountains\)", ["Autostrada Asti-Cuneo S.p.A."]),
    ("it-sav", r"MOUNTAIN TARIFF", ["Società Autostrade Valdostane S.p.A."]),
    ("it-a22", r"pianura", ["Autostrada del Brennero S.p.A."]),
]
TITLES = {
    "it-satap-a4": "SATAP: A4 Torino-Milano toll information (unit tariffs for users, VAT and ANAS fee included)",
    "it-itp-a21": "Ivrea Torino Piacenza: A21 toll information (unit rates, VAT and ANAS fee included)",
    "it-itp-a5": "Ivrea Torino Piacenza: A55/A5 toll information (unit rates, VAT and ANAS fee included)",
    "it-asti-cuneo": "Asti-Cuneo: A33 toll information (unit rates for users, VAT and ANAS fee included)",
    "it-sav": "SAV: A5 Quincinetto-Aosta toll information (unit tariffs for users, VAT and ANAS fee included)",
    "it-a22": "Autostrada del Brennero: A22 toll tariffs in force from 1 January (PDF)",
}
PAGE_NAMES = {"it-satap-a4": "SATAP (A4 Torino-Milano)", "it-itp-a21": "Ivrea Torino Piacenza (A21)", "it-itp-a5": "Ivrea Torino Piacenza (A5, A55)",
              "it-asti-cuneo": "Asti-Cuneo (A33)", "it-sav": "SAV (A5 Quincinetto-Aosta)", "it-a22": "Autostrada del Brennero (A22)"}
AXLES = [(2, 2, "B"), (3, 3, "3"), (4, 4, "4"), (5, 0, "5")]


def page_url(fetched, pid):
    for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]:
        if f["file"].startswith(pid + "."):
            return f["url"]
    sys.exit(f"{pid}: not in the manifest")


NUM = r"(\d[.,]\d{3,6}|[–-])"


def text_of(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith(".html"):
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t.replace("\xa0", " "))


def page_rates(fetched, pid, row, year):
    """The page's rates for classes A, B, 3, 4, 5 on the row, if the page
    gives them for the year; else None and why."""
    for ext in (".html", ".txt"):
        path = os.path.join(fetched, pid + ext)
        if os.path.exists(path):
            break
    else:
        return None, "not fetched"
    t = text_of(path)
    if pid == "it-a22":
        # The PDF: "in vigore dal 1° gennaio <year>", then per class the
        # unit rate, the two ANAS quotas, the total and the total with VAT,
        # the plain table after "pianura".
        if not re.search(rf"in vigore dal 1° gennaio {year}", t, re.I):
            return None, f"not in force from 1 January {year}"
        i = re.search(row, t, re.I)
        if not i:
            return None, "plain table not found"
        rows = re.findall(r"\b(A|B|3|4|5) (\d,\d{5}) (\d,\d{4}) (\d,\d{4}) (\d,\d{5}) (\d,\d{5})", t[i.end():])
        got = {r[0]: float(r[5].replace(",", ".")) for r in rows[:5]}
        if sorted(got) != ["3", "4", "5", "A", "B"]:
            return None, "plain rows not found"
        return [got[c] for c in "AB345"], ""
    head = re.search(r"VEHICLE CLASS(?:ES)? A B 3 4 5", t, re.I)
    if not head:
        return None, "class header not found"
    # The year: "(€/KM <year>)", or rates "valid from 1 January <y>" with
    # each later year's increase 0,00% up to the year.
    m = re.search(r"€/KM (\d{4})", t, re.I)
    if m:
        if m.group(1) != str(year):
            return None, f"rates for {m.group(1)}"
    else:
        m = re.search(r"valid from 1 January (\d{4})", t, re.I)
        if not m or not all(re.search(rf"\b{y} 0,00%", t) for y in range(int(m.group(1)) + 1, year + 1)):
            return None, f"rates not for {year}"
    if not re.search(r"VAT \(22%\).{0,40}ANAS fee", t):
        return None, "VAT and ANAS fee not stated as included"
    r = re.search(row + r"[^0-9–]*?" + " ".join([NUM] * 5), t[head.end():head.end() + 2000], re.I)
    if not r:
        return None, "row not found"
    vals = [None if v in "–-" else float(v.replace(",", ".")) for v in r.groups()]
    if any(v is None for v in vals[1:]):
        return None, "row has no rates"
    return vals, ""
# Pedemontana Lombarda's free-flow classes: 3 trucks, 4 articulated or
# with trailer.
PEDEMONTANA = {"B": "3", "3": "3", "4": "4", "5": "4"}
VAT = 1.22


def operator_rows(transcribed, fetched, year):
    rows, used, pages = [], {}, {}
    for pid, row, keys in PAGES:
        vals, why = page_rates(fetched, pid, row, year)
        print(pid, row, vals if vals else why)
        if vals:
            for k in keys:
                pages[k] = (pid, vals)
    for op, ref, sheet, stretch in OPS:
        key = f"{op}|{ref}" if ref else op
        if key in pages:
            pid, vals = pages[key]
            used["page:" + pid] = pid
            for (lo, hi, cl), v in zip(AXLES, vals[1:]):
                rows.append(row_for(key, lo, hi, v))
            continue
        if not sheet:
            continue
        d = json.load(open(os.path.join(transcribed, f"it-mit-{sheet}.json"), encoding="utf-8"))
        used[sheet] = d
        for lo, hi, cl in AXLES:
            if sheet == "pedemontana-lombarda":
                r = d["rates"][PEDEMONTANA[cl]]
                unit, anas = r[stretch], r["anas"]
            else:
                r = d["rates"][stretch] if stretch else d["rates"]
                unit, anas = r[cl]["unit"], r[cl]["anas"] or 0
            rows.append(row_for(key, lo, hi, round((unit + anas) * VAT, 5)))
    return rows, used


def row_for(key, lo, hi, rate):
    row = {"component": "toll", "road": "motorway", "operator": key, "min_kg": 3501, "min_axles": lo, "rate": rate}
    if hi:
        row["max_axles"] = hi
    if lo == 2:
        del row["min_axles"]
    return row


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
    ops, used = operator_rows(transcribed, fetched, int(valid_from[:4]))
    rows += ops
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": valid_from, "valid_to": f"{valid_from[:4]}-12-31",
        "name": "Italian motorway tolls (ESTIMATE: each concession's unit rate per km)",
        "law": "Estimate. Italian motorway tolls are each concession's unit rate per km, by vehicle class (A, B by height for two axles; 3, 4, 5 by axles) and by plain or mountain stretch, plus the ANAS surcharge (law 102/2009 art. 19 c. 9-bis), times the km between toll stations, plus 22% VAT, rounded to 10 cents (the concession agreements with the Ministry, under the State's laws and CIPE resolutions). "
               "No station-to-station table can be fetched, so the route's km on toll motorways (OpenStreetMap ways tagged toll=yes) are priced by the operator OpenStreetMap gives the ways: "
               + (f"{', '.join(PAGE_NAMES[k[5:]] for k in used if k.startswith('page:'))} at the unit rates for users (VAT and ANAS fee included) their own pages give for {valid_from[:4]}; " if any(k.startswith("page:") for k in used) else "")
               + f"the other concessions with a published sheet at their unit rate for 2025, ANAS surcharge and VAT included, as their sheets sent to the Ministry of Infrastructure and Transport (Directive (EU) 2022/362 art. 11, published March 2025) state them (the 2026 change, 1.5% on most networks, isn't applied to them: the Ministry's note couldn't be found and their pages give no rates as text), each concession's plain-stretch rate unless it has only mountain stretches; "
               f"Autostrade per l'Italia's network and the concessions without rates in their sheet at Autostrade per l'Italia's plain-stretch unit rate, VAT included, in force from {valid_from}: class B {pl[1]:.5f}, 3 {pl[2]:.5f}, 4 {pl[3]:.5f}, 5 {pl[4]:.5f} euro per km. "
               f"Pedemontana Lombarda's classes are its own (3 trucks up to three axles, 4 articulated or with trailer). Mountain stretches cost about {up}% more on ASPI's network (class 5 {mo[4]:.5f}), SATAP's A4 east of Novara Est (its tariff B) and CAV's Passante di Mestre and A57 are priced at their own rates (placed by the motorway junctions in OpenStreetMap), SITAF's A32 at its Avigliana rate (Salbertrand's is 2% lower), Milan's ring roads and other open-system stretches charge fixed tolls, and the rounding isn't modelled, so the true toll can differ.",
        "sources": [{"title": "Autostrade per l'Italia: come si calcola il pedaggio (unit rates per km, VAT included)", "url": "https://www.autostrade.it/it/servizi-al-cliente/pedaggio/come-si-calcola-il-pedaggio"}]
        + [{"title": TITLES[d], "url": page_url(fetched, d)} for k, d in used.items() if k.startswith("page:")]
        + [{"title": f"MIT: {d['operator']}, tariff sheet (Directive (EU) 2022/362 art. 11), p. {d['source']['page']}", "url": d["source"]["url"]} for k, d in used.items() if not k.startswith("page:")],
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
