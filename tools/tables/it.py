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
# Tangenziale di Napoli), take ASPI's rate; Ivrea Torino
# Piacenza's A5, A4/A5 and A55 only where its page (PAGES) gives the rates,
# Superstrada Pedemontana Veneta where Autostrade per l'Italia's tariff
# file (FILE_RATES) does.
OPS = [
    ("Superstrada Pedemontana Veneta S.p.A.", "", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A26|Lago Maggiore", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A1|mountain", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A26|mountain", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A23|mountain", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A16|mountain", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A27|mountain", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A7", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A10", "", ""),
    ("Autostrade per l'Italia S.p.A.", "A12", "", ""),
    ("Autostrada del Brennero S.p.A.", "", "a22-brennero", ""),
    ("Autostrada del Brennero S.p.A.", "A22|Brennero-Affi", "a22-brennero", ""),
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
    ("it-a22", r"montagna", ["Autostrada del Brennero S.p.A.|A22|Brennero-Affi"]),
    ("it-autovia-padana", r"A21 PIACENZA-BRESCIA AND FIORENZUOLA D.ARDA BRANCH .A. FARES", ["Autovia Padana S.p.A."]),
]
# Concessions priced at the unit rate Autostrade per l'Italia's toll
# calculator file gives them (its traffic site's tariffe.json: by company
# and network, plain and mountain rate, ANAS fee and VAT, as its form
# prices any station pair): fetch.py's file, the operator key, the company
# and network, the rate. The file's own rates must be those of ASPI's page
# for the year (main), or it isn't used.
FILE_RATES = [
    ("it-aspi-unit-rates", "Superstrada Pedemontana Veneta S.p.A.", 41, 32, "tarP"),
    # The A26 north of the Lago Maggiore station, which charges its km at
    # ASPI's mountain rate (tools/roads/build.py, TOLLED).
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A26|Lago Maggiore", 6, 1, "tarM"),
    # ASPI's mountain stretches its route calculator prices at that rate
    # (browser/it-aspi-mountain.txt): those tools/roads/build.py places
    # (MOUNTAIN), and its A7 Serravalle-Genova, A10 Genova-Savona and A12
    # Genova-Sestri Levante whole (the A12 Roma-Civitavecchia has its own
    # key, priced at its barriers).
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A1|mountain", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A26|mountain", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A23|mountain", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A16|mountain", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A27|mountain", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A7", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A10", 6, 1, "tarM"),
    ("it-aspi-unit-rates", "Autostrade per l'Italia S.p.A.|A12", 6, 1, "tarM"),
]
# Concessions whose rates for the year are published only as an image,
# transcribed (transcribed/<file>.json, "user" rates with VAT and ANAS fee):
# the file, its section, the operator keys it prices.
IMAGES = [
    ("it-cav-2026", "A4", ["CAV S.p.A."]),
    ("it-cav-2026", "A57", ["CAV S.p.A.|A57"]),
    ("it-cav-2026", "Passante", ["CAV S.p.A.|A4|Passante"]),
    ("it-a4bspd-2026", "A4", ["Autostrada Brescia Verona Vicenza Padova S.p.A."]),
    ("it-rav-2026", "A5", ["RAV Raccordo Autostradale Valle d'Aosta S.p.A."]),
]
# Concessions whose own page states the year's increase of the unit
# rates (the Ministry's adjustment, applied to the unit rate without the
# ANAS fee): fetch.py's file, the statement (its rate), the year's heading,
# and the operator keys. The 2025 sheet's unit rate times (1 + increase),
# to 5 decimals, gives the year's: Brescia-Padova's 2026 image bears that
# rule out exactly.
ASTM_HEAD = r"Dal 1° gennaio (\d{4}) entrano in vigore gli adeguamenti delle tariffe di pedaggio autostradale"
INCREASES = [
    ("it-serravalle-pedaggio",
     r"le tariffe autostradali unitarie chilometriche di competenza di Milano Serravalle Milano Tangenziali S\.p\.A\. subiranno un aumento corrispondente all.indice di inflazione programmatico pari a (\d+,\d+)%",
     r"ADEGUAMENTO TARIFFARIO DAL 1° GENNAIO (\d{4})", ["Milano Serravalle - Milano Tangenziali S.p.A.|A7"]),
    # ASTM group's notices to users ("Comunicato all'utenza - tariffe <year>").
    ("it-adf-tariffe", r"Per la Società Autostrada dei Fiori S\.p\.A\. la variazione tariffaria è pari a \+? ?(\d+,\d+)%",
     ASTM_HEAD, ["Autostrada dei Fiori S.p.A."]),
    ("it-salt-tariffe", r"Per la Società Autostrada Ligure Toscana p\.a\. la variazione tariffaria è pari a \+? ?(\d+,\d+)%",
     ASTM_HEAD, ["Società Autostrada Ligure Toscana p.a.|A15"]),
    ("it-te-tariffe", r"Per Tangenziale Esterna S\.p\.A\. \(A58-TEEM\) la variazione tariffaria è pari a \+? ?(\d+,\d+)%",
     ASTM_HEAD, ["Tangenziale Esterna S.p.A."]),
]
TITLES = {
    "it-satap-a4": "SATAP: A4 Torino-Milano toll information (unit tariffs for users, VAT and ANAS fee included)",
    "it-itp-a21": "Ivrea Torino Piacenza: A21 toll information (unit rates, VAT and ANAS fee included)",
    "it-itp-a5": "Ivrea Torino Piacenza: A55/A5 toll information (unit rates, VAT and ANAS fee included)",
    "it-asti-cuneo": "Asti-Cuneo: A33 toll information (unit rates for users, VAT and ANAS fee included)",
    "it-sav": "SAV: A5 Quincinetto-Aosta toll information (unit tariffs for users, VAT and ANAS fee included)",
    "it-a22": "Autostrada del Brennero: A22 toll tariffs in force from 1 January (PDF)",
    "it-autovia-padana": "Autovia Padana: A21 Piacenza-Brescia toll information (unit tariffs for users, the 'A' fares)",
    "it-sat-pedaggio": "SAT: toll page, unit rates per km from 1 January (A12 Livorno-Civitavecchia, mountain; ANAS fee and VAT included)",
    "it-brebemi-pedaggi": "Brebemi: toll page, unit rates per km from 1 January (A35, plain; VAT and ANAS fee included) and the yearly increases",
    "it-pedemontana-rates": "Autostrada Pedemontana Lombarda: rates (per section, company rate and ANAS fee, VAT excluded)",
    "it-adf-tariffe": "Autostrada dei Fiori (A6): notice to users, tariffs from 1 January (the year's change of the unit rates, set by the MIT's note)",
    "it-salt-tariffe": "SALT (A15): notice to users, tariffs from 1 January (the year's change of the unit rates, set by the MIT's note)",
    "it-te-tariffe": "Tangenziale Esterna (A58): notice to users, tariffs from 1 January (the year's change of the unit rates, set by the MIT's note)",
    "it-serravalle-pedaggio": "Milano Serravalle: toll page, the year's increase of the unit rates (MIT communication of 31/12/2025 prot. 40030)",
    "it-aspi-unit-rates": "Autostrade per l'Italia, Info viabilità: its toll calculator's unit rates by company (tariffe.json; plain and mountain, ANAS fee, VAT)",
}
IMAGE_TITLES = {"it-cav-2026": "CAV: toll rates (unit rates per km by section, ANAS fee and VAT included, published as an image; transcribed)",
                "it-rav-2026": "RAV: unit rates per km from 1 January (A5 Aosta-Courmayeur, mountain; VAT and ANAS fee included), in its service charter (PDF, page 11; transcribed)",
                "it-a4bspd-2026": "Autostrada Brescia Verona Vicenza Padova: unit rates per km from 1 January (A4, A31; excluding VAT, ANAS quota apart; an image in the page, transcribed)"}
PAGE_NAMES = {"image:it-cav-2026": "CAV (A4, A57, Passante di Mestre)", "image:it-rav-2026": "RAV (A5 Aosta-Courmayeur)", "image:it-a4bspd-2026": "Brescia-Padova (A4 Brescia-Padova, A31)", "it-satap-a4": "SATAP (A4 Torino-Milano)", "it-itp-a21": "Ivrea Torino Piacenza (A21)", "it-itp-a5": "Ivrea Torino Piacenza (A5, A55)",
              "it-asti-cuneo": "Asti-Cuneo (A33)", "it-sav": "SAV (A5 Quincinetto-Aosta)", "it-a22": "Autostrada del Brennero (A22; Brennero-Affi at its mountain rate, placed by the Affi junction in OpenStreetMap)",
              "it-autovia-padana": "Autovia Padana (A21 Piacenza-Brescia)",
              "it-pedemontana-rates": "Pedemontana Lombarda (A36, A59, A60)",
              "it-sat-pedaggio": "SAT (A12 Livorno-Civitavecchia)",
              "it-brebemi-pedaggi": "Brebemi (A35)",
              "inc:it-adf-tariffe": "Autostrada dei Fiori (A6; its 2025 unit rate raised by the change its notice states)",
              "inc:it-salt-tariffe": "SALT (A15; its 2025 unit rate raised by the change its notice states)",
              "inc:it-te-tariffe": "Tangenziale Esterna (A58; its 2025 unit rate raised by the change its notice states)",
              "inc:it-serravalle-pedaggio": "Milano Serravalle (A7; its 2025 unit rate raised by the increase its page states)",
              "it-aspi-unit-rates": "Superstrada Pedemontana Veneta and Autostrade per l'Italia's mountain stretches as its route calculator prices them (the A1 Bologna-Calenzano, A7 Serravalle-Genova, A10 Genova-Savona, A12 Genova-Sestri Levante, A16 Baiano-Candela, A23 Carnia-Tarvisio, A26 Genova Voltri-Alessandria Sud and Gravellona Toce-Lago Maggiore, A27 Conegliano-Belluno; their rates in Autostrade per l'Italia's toll calculator file, which gives Autostrade per l'Italia's own plain rates as its page does)"}
CAS = "Consorzio per le Autostrade Siciliane"
MISE = "Milano Serravalle - Milano Tangenziali S.p.A."
SITAF = "SITAF S.p.A."
# Open systems priced at their barriers (it_barriers.py): Autostrade per
# l'Italia's A8 Milano-Varese, A9 Lainate-Como and A12 Roma-Civitavecchia
# (the roads data splits it from the A12 Genova-Sestri Levante), Salerno
# Pompei Napoli's A3, the Tangenziale di Torino.
OPEN = ("Autostrade per l'Italia S.p.A.|A8", "Autostrade per l'Italia S.p.A.|A9", "Autostrade per l'Italia S.p.A.|A12|Roma-Civitavecchia",
        "Salerno Pompei Napoli S.p.A.|A3", "Ivrea Torino Piacenza S.p.A.|A55")
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
        # Ten class rows, A to 5 twice: the mountain table, then the plain
        # one (the labels "TARIFFA DI MONTAGNA/PIANURA" sit beside the rows).
        rows = re.findall(r"\b(A|B|3|4|5) (\d,\d{5}) (\d,\d{4}) (\d,\d{4}) (\d,\d{5}) (\d,\d{5})", t)
        mo, pl = re.search(r"MONTAGNA", t), re.search(r"PIANURA", t)
        if [r[0] for r in rows] != list("AB345") * 2 or not mo or not pl or mo.start() > pl.start():
            return None, "mountain and plain rows not found"
        got = {r[0]: float(r[5].replace(",", ".")) for r in (rows[:5] if re.search("montagna", row, re.I) else rows[5:])}
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
        if not m or not all(re.search(rf"\b{y} (?:Increase )?0,00%", t) for y in range(int(m.group(1)) + 1, year + 1)):
            return None, f"rates not for {year}"
    if not re.search(r"VAT \(22%\).{0,40}ANAS fee", t):
        # "Unit tariffs for users" with no statement of what they include:
        # taken as VAT and ANAS fee included only if they're within a few
        # per cent of the Ministry's 2025 sheet at that (operator_rows).
        if not re.search(r"UNIT TARIFFS FOR USERS \(€/KM", t, re.I):
            return None, "VAT and ANAS fee not stated as included"
        USERS_ONLY.add(pid)
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


USERS_ONLY = set()
# Pedemontana Lombarda's rates page: per section, its classes 1-4: the
# company rate and the ANAS fee (VAT excluded), and their sum "in
# application to the user since 1/1/<year>".
PED_SECTIONS = {"A36-A": r"Section A \(A36\)", "A59": r"Tang\. Como \(A59\)", "A60": r"Tang\. Varese \(A60\)"}
CLS4 = r"Class ?1 ?Class ?2 ?Class ?3 ?Class ?4 ?"


# Concessions whose toll page gives the year's rates for classes A, B, 3,
# 4, 5 as text, ANAS fee and VAT included: fetch.py's file, the heading
# naming the year, the rates (five groups), the operator key.
N5 = " ".join([r"(\d,\d{5})"] * 5)
TEXT_PAGES = [
    ("it-sat-pedaggio",
     r"TARIFFE UNITARIE SAT \(comprensive di importo di competenza ANAS legge 102/2009 e 122/2010 e di IVA\) 1° gennaio (\d{4})",
     r"CLASSI DI VEICOLO A B 3 4 5 Tariffa di montagna €/Km " + N5, "SAT p.A."),
    ("it-brebemi-pedaggi",
     r"il valore della tariffa unitaria valida dal 1 gennaio (\d{4}) suddivisa nelle 5 classi veicolari",
     r"Classi Tariffe da applicare dal \d\d/\d\d/\d{4} \(€/km con IVA\) A (\d,\d{5}) B (\d,\d{5}) 3 (\d,\d{5}) 4 (\d,\d{5}) 5 (\d,\d{5})",
     "Società di Progetto Brebemi S.p.A"),
]


def text_page(fetched, pid, head, rates, year):
    """A TEXT_PAGES page's rates for classes A, B, 3, 4, 5, if it gives
    them for the year; else None."""
    path = os.path.join(fetched, pid + ".html")
    if not os.path.exists(path):
        return None
    t = text_of(path)
    h, m = re.search(head, t), re.search(rates, t)
    print(pid, h.group(1) if h else "no heading", m.groups() if m else "no rates")
    if not h or not m or h.group(1) != str(year):
        return None
    return [float(x.replace(",", ".")) for x in m.groups()]


def pedemontana_page(fetched, year):
    """The sheet's rates shape ({class: {section: unit, "anas": fee}})
    from Pedemontana's page, if it gives them for the year."""
    path = os.path.join(fetched, "it-pedemontana-rates.html")
    if not os.path.exists(path):
        return None
    t = text_of(path)
    n4 = " ?".join([r"(\d,\d{5})"] * 4)
    out = {str(k): {} for k in range(1, 5)}
    for sec, label in PED_SECTIONS.items():
        m = re.search(label + r".{0,400}?" + CLS4 + n4 + r" ?Fee pursuant.{0,80}?" + CLS4 + n4
                      + r" ?Rate in application to the user since 1/1/(\d{4}) ?" + CLS4 + n4, t)
        if not m:
            print("it-pedemontana-rates:", sec, "not found")
            return None
        v = [float(x.replace(",", ".")) for x in m.groups()[:8] + m.groups()[9:]]
        if m.group(9) != str(year):
            print("it-pedemontana-rates: rates since", m.group(9))
            return None
        for k in range(4):
            assert round(v[k] + v[4 + k], 5) == v[8 + k], (sec, v)  # company rate + fee = the user's
            out[str(k + 1)][sec] = v[k]
            out[str(k + 1)]["anas"] = v[4 + k]
    print("it-pedemontana-rates", year, out)
    return out


def sheet_user(d, cl, stretch=""):
    """The 2025 sheet's rate for a class with the ANAS fee and VAT."""
    r = d["rates"][stretch] if stretch else d["rates"]
    if d.get("vat_included"):  # the sheet's rate has both already
        return r[cl]["unit"]
    return round((r[cl]["unit"] + (r[cl]["anas"] or 0)) * VAT, 5)


def file_rates(fetched, aspi_plain):
    """FILE_RATES' rates by operator key (classes A, B, 3, 4, 5 with VAT
    and the ANAS fee), if the file gives Autostrade per l'Italia's plain
    rates as its page does (aspi_plain: classes A, B, 3, 4, 5)."""
    path = os.path.join(fetched, "it-aspi-unit-rates.json")
    if not aspi_plain or not os.path.exists(path):
        return {}
    socs = {(x["cSoc"], x["cRet"]): {c.get("tDesCla"): c for c in x["classi"]} for x in json.load(open(path, encoding="utf-8"))["tariffeUnitarieSocieta"]}
    user = lambda c, k: round((c[k] + c["tarComA"]) * (1 + c["iva"] / 100), 5)
    own = socs.get((6, 1), {})
    mine = [user(own[cl], "tarP") if cl in own else None for cl in "AB345"]
    if mine[1:] != aspi_plain[1:]:
        print("it-aspi-unit-rates: Autostrade per l'Italia's rates", mine, "aren't its page's", aspi_plain, "- file not used")
        return {}
    out = {}
    for pid, key, soc, ret, k in FILE_RATES:
        c = socs.get((soc, ret))
        if not c or any(cl not in c or c[cl][k] <= 0 for cl in "B345"):
            sys.exit(f"{pid}: no {k} rates for company {soc}, network {ret}")
        out[key] = (pid, [user(c[cl], k) if cl in c else None for cl in "AB345"])
        print(pid, key, out[key][1])
    return out


# The rows the builder checks against Autostrade per l'Italia's toll
# calculator file: operator key -> company, network and rate there.
CHECK = {
    "Autostrada Asti-Cuneo S.p.A.": (43, 1, "tarM"), "Autostrada Brescia Verona Vicenza Padova S.p.A.": (1, 1, "tarP"),
    "Autostrada del Brennero S.p.A.": (2, 1, "tarP"), "Autostrada dei Fiori S.p.A.": (26, 1, "tarM"),
    "Autovia Padana S.p.A.": (49, 1, "tarP"), "CAV S.p.A.": (54, 1, "tarM"), "CAV S.p.A.|A4|Passante": (54, 1, "tarP"),
    "Concessioni del Tirreno S.p.A.": (74, 1, "tarP"), "Concessioni del Tirreno S.p.A.|A10": (75, 1, "tarM"),
    "Ivrea Torino Piacenza S.p.A.": (98, 1, "tarP"), "Ivrea Torino Piacenza S.p.A.|A21": (97, 1, "tarP"),
    "Milano Serravalle - Milano Tangenziali S.p.A.|A7": (7, 1, "tarP"), "RAV Raccordo Autostradale Valle d'Aosta S.p.A.": (29, 1, "tarM"),
    "SAT p.A.": (28, 1, "tarM"), "SATAP S.p.A.|A4": (14, 1, "tarP"), "SATAP S.p.A.|A4|Novara Est-Milano": (14, 1, "tarM"),
    "Società Autostrada Ligure Toscana p.a.|A15": (11, 1, "tarM"), "Società Autostrade Alto Adriatico S.p.A.": (78, 1, "tarP"),
    "Società Autostrade Valdostane S.p.A.": (17, 1, "tarM"), "Società di Progetto Brebemi S.p.A": (80, 1, "tarP"),
    "Strada dei Parchi S.p.A.": (5, 1, "tarM"), "Tangenziale Esterna S.p.A.": (81, 1, "tarP"),
}


def cross_check(fetched, rows):
    """Warns (GitHub Actions ::warning lines) where a concession's row
    differs from Autostrade per l'Italia's toll calculator file by more
    than 0.25%: a year's change missed (mostly 1.5%) shows, while pages
    giving fewer decimals (SAV's three) and Autovia Padana's 'A' fares
    (0.15% above the file's) don't."""
    path = os.path.join(fetched, "it-aspi-unit-rates.json")
    if not os.path.exists(path):
        return
    socs = {(x["cSoc"], x["cRet"]): {c.get("tDesCla"): c for c in x["classi"]} for x in json.load(open(path, encoding="utf-8"))["tariffeUnitarieSocieta"]}
    n = 0
    for r in rows:
        key, cl = r.get("operator"), {None: "B", 3: "3", 4: "4", 5: "5"}[r.get("min_axles")]
        if key not in CHECK:
            continue
        soc, ret, k = CHECK[key]
        c = socs.get((soc, ret), {}).get(cl)
        if not c or c[k] <= 0:
            print(f"::warning::it: {key} isn't in Autostrade per l'Italia's toll calculator file (company {soc}, network {ret})")
            continue
        want = round((c[k] + c["tarComA"]) * (1 + c["iva"] / 100), 5)
        n += 1
        if abs(r["rate"] / want - 1) > 0.0025:
            print(f"::warning::it: {key} class {cl} at {r['rate']}, Autostrade per l'Italia's toll calculator file {want}")
    print("it: rows checked against the toll calculator file:", n)


def operator_rows(transcribed, fetched, year, own_tables=(CAS,), aspi_plain=None):
    rows, used, pages = [], {}, {}
    pages.update(file_rates(fetched, aspi_plain))
    for pid, row, keys in PAGES:
        vals, why = page_rates(fetched, pid, row, year)
        print(pid, row, vals if vals else why)
        if vals:
            for k in keys:
                pages[k] = (pid, vals)
    ped = pedemontana_page(fetched, year)
    for pid, head, rates, key in TEXT_PAGES:
        vals = text_page(fetched, pid, head, rates, year)
        if vals:
            pages[key] = (pid, vals)
    inc = {}
    for pid, stmt, head, keys in INCREASES:
        path = os.path.join(fetched, pid + ".html")
        t = text_of(path) if os.path.exists(path) else ""
        h, m = re.search(head, t), re.search(stmt, t)
        print(pid, h.group(1) if h else "no year", m.group(1) if m else "no increase stated")
        if h and m and h.group(1) == str(year):
            for k in keys:
                inc[k] = (pid, float(m.group(1).replace(",", ".")) / 100)
    for name, section, keys in IMAGES:
        d = json.load(open(os.path.join(transcribed, name + ".json"), encoding="utf-8"))
        if d["valid_from"][:4] != str(year):
            print(name, "rates for", d["valid_from"])
            continue
        # "user" with VAT and the ANAS fee, or unit and ANAS fee without VAT.
        vals = [r["user"] if "user" in r else round((r["unit"] + r["anas"]) * VAT, 5)
                for r in (d["rates"][section][c] for c in "AB345")]
        print(name, section, vals)
        for k in keys:
            pages[k] = ("image:" + name, vals)
    # The Consorzio per le Autostrade Siciliane's A18 and A20 are priced by
    # entry and exit in their own table (it_cas.py), Milan's ring roads,
    # SITAF's A32 (with its few ways to the Fréjus tunnel, whose own table
    # prices it), the A8, A9 and Tangenziale di Torino at their barriers
    # (it_barriers.py): nothing here.
    for key in list(own_tables) + [f"{MISE}|{r}" for r in ("A50", "A51", "A52")]:
        for lo, hi, cl in AXLES:
            rows.append(row_for(key, lo, hi, 0))
    for op, ref, sheet, stretch in OPS:
        key = f"{op}|{ref}" if ref else op
        if op in own_tables or key in own_tables:
            continue
        if key in pages and pages[key][0] in USERS_ONLY and sheet:
            pid, vals = pages[key]
            d = json.load(open(os.path.join(transcribed, f"it-mit-{sheet}.json"), encoding="utf-8"))
            ratio = [v / sheet_user(d, cl, stretch) for (lo, hi, cl), v in zip(AXLES, vals[1:])]
            if not all(0.97 < x < 1.08 for x in ratio):
                print(pid, "rates aren't the 2025 sheet's with VAT and the ANAS fee, moved by a yearly change:", ratio)
                del pages[key]
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
        if sheet == "pedemontana-lombarda" and ped:
            used.pop(sheet)  # the page's rates, not the sheet's
            used["page:it-pedemontana-rates"] = "it-pedemontana-rates"
            for lo, hi, cl in AXLES:
                r = ped[PEDEMONTANA[cl]]
                rows.append(row_for(key, lo, hi, round((r[stretch] + r["anas"]) * VAT, 5)))
            continue
        if key in inc:
            pid, x = inc[key]
            used["page:inc:" + pid] = "inc:" + pid
            r = d["rates"][stretch] if stretch else d["rates"]
            for lo, hi, cl in AXLES:
                rows.append(row_for(key, lo, hi, round((round(r[cl]["unit"] * (1 + x), 5) + r[cl]["anas"]) * VAT, 5)))
            continue
        for lo, hi, cl in AXLES:
            if sheet == "pedemontana-lombarda":
                r = d["rates"][PEDEMONTANA[cl]]
                rate = round((r[stretch] + r["anas"]) * VAT, 5)
            else:
                rate = sheet_user(d, cl, stretch)
            rows.append(row_for(key, lo, hi, rate))
    return rows, used


def image_url(transcribed, name):
    """A transcription's page, or its file where "page" is a page number."""
    src = json.load(open(os.path.join(transcribed, name + ".json"), encoding="utf-8"))["source"]
    return src["page"] if isinstance(src.get("page"), str) else src["url"]


def row_for(key, lo, hi, rate):
    row = {"component": "toll", "road": "motorway", "operator": key, "min_kg": 3501, "min_axles": lo, "rate": rate}
    if hi:
        row["max_axles"] = hi
    if lo == 2:
        del row["min_axles"]
    return row


MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
          "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}


def write(out, valid_from, pl, mo, ops, used, transcribed, fetched, text):
    """The table: Autostrade per l'Italia's rates (pl, mo: plain and
    mountain, classes A, B, 3, 4, 5) by axles, then each concession's."""
    rows = [
        {"component": "toll", "road": "motorway", "min_kg": 3501, "max_axles": 2, "rate": pl[1]},
        {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": pl[2]},
        {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 4, "max_axles": 4, "rate": pl[3]},
        {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 5, "rate": pl[4]},
    ]
    up = round(100 * (mo[4] / pl[4] - 1))
    rows += ops
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": valid_from, "valid_to": f"{valid_from[:4]}-12-31",
        "name": "Italian motorway tolls (ESTIMATE: each concession's unit rate per km)",
        "law": "Estimate. Italian motorway tolls are each concession's unit rate per km, by vehicle class (A, B by height for two axles; 3, 4, 5 by axles) and by plain or mountain stretch, plus the ANAS surcharge (law 102/2009 art. 19 c. 9-bis), times the km between toll stations, plus 22% VAT, rounded to 10 cents (the concession agreements with the Ministry, under the State's laws and CIPE resolutions). "
               "No station-to-station table can be fetched, so the route's km on toll motorways (OpenStreetMap ways tagged toll=yes) are priced by the operator OpenStreetMap gives the ways: "
               + (f"{', '.join(PAGE_NAMES[k[5:]] for k in used if k.startswith('page:'))} at the {valid_from[:4]} rates their own pages give (with VAT and the ANAS fee); " if any(k.startswith("page:") for k in used) else "")
               + text["own"]
               + f"the other concessions with a published sheet at their unit rate for 2025, ANAS surcharge and VAT included, as their sheets sent to the Ministry of Infrastructure and Transport (Directive (EU) 2022/362 art. 11, published March 2025) state them {text['sheets']}, each concession's plain-stretch rate unless it has only mountain stretches; "
               f"{text['aspi']}: class B {pl[1]:.5f}, 3 {pl[2]:.5f}, 4 {pl[3]:.5f}, 5 {pl[4]:.5f} euro per km. "
               f"Pedemontana Lombarda's classes are its own (3 trucks up to three axles, 4 articulated or with trailer). Mountain stretches cost about {up}% more on ASPI's network (class 5 {mo[4]:.5f}), SATAP's A4 east of Novara Est (its tariff B) and CAV's Passante di Mestre and A57 are priced at their own rates (placed by the motorway junctions in OpenStreetMap); the other open-system stretches charge fixed tolls, and the rounding isn't modelled, so the true toll can differ.",
        "sources": [text["aspi_source"]]
        + [{"title": TITLES[d.removeprefix("inc:")], "url": page_url(fetched, d.removeprefix("inc:"))} for k, d in used.items() if k.startswith("page:") and not d.startswith("image:")]
        + [{"title": IMAGE_TITLES[d[6:]], "url": image_url(transcribed, d[6:])} for k, d in used.items() if k.startswith("page:image:")]
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


def main(transcribed, fetched, out):
    """The current table: Autostrade per l'Italia's rates from its page."""
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
    ops, used = operator_rows(transcribed, fetched, int(valid_from[:4]), own_tables=(CAS, SITAF) + OPEN, aspi_plain=pl)
    cross_check(fetched, ops)
    write(out, valid_from, pl, mo, ops, used, transcribed, fetched, {
        "aspi": f"Autostrade per l'Italia's network and the concessions without rates in their sheet at Autostrade per l'Italia's plain-stretch unit rate, VAT included, in force from {valid_from}",
        "aspi_source": {"title": "Autostrade per l'Italia: come si calcola il pedaggio (unit rates per km, VAT included)", "url": "https://www.autostrade.it/it/servizi-al-cliente/pedaggio/come-si-calcola-il-pedaggio"},
        "sheets": "(the year's change, 1.5% on most networks in 2026, isn't applied to them: the Ministry's note couldn't be found, and their own pages state neither the year's rates nor the change)",
        "own": "the Consorzio per le Autostrade Siciliane's A18 and A20 by entry and exit in their own table (it-cas), and the open systems of Milan's ring roads (A50, A51, A52), SITAF's A32 Torino-Bardonecchia, Autostrade per l'Italia's A8 Milano-Varese, A9 Lainate-Como and A12 Roma-Civitavecchia, Salerno Pompei Napoli's A3 and the Tangenziale di Torino (A55) at their barriers (it-barriers), not here; "})


def sheets(transcribed, out, year):
    """A past year's table from the Ministry's sheets alone (the 2025
    sheets, published March 2025): Autostrade per l'Italia's plain and
    mountain rates from its own sheet, with the ANAS fee and VAT; the
    Consorzio per le Autostrade Siciliane's A18 and A20 at those too (its
    tables for the year weren't archived)."""
    d = json.load(open(os.path.join(transcribed, "it-mit-aspi.json"), encoding="utf-8"))
    if d["valid_from"][:4] != str(year):
        sys.exit(f"it-mit-aspi: the sheet is for {d['valid_from'][:4]}, not {year}")
    pl = [None] + [sheet_user(d, cl) for cl in "B345"]
    mo = [None] + [round((d["mountain"][cl]["unit"] + d["mountain"][cl]["anas"]) * VAT, 5) for cl in "B345"]
    ops, used = operator_rows(transcribed, os.devnull, year, own_tables=())
    write(out, f"{year}-01-01", pl, mo, ops, used, transcribed, os.devnull, {
        "aspi": f"Autostrade per l'Italia's network, the Consorzio per le Autostrade Siciliane's A18 and A20 (its {year} tables weren't archived) and the concessions without rates in their sheet at Autostrade per l'Italia's plain-stretch unit rate for {year} as its sheet gives it, with the ANAS surcharge and VAT",
        "aspi_source": {"title": f"MIT: {d['operator']}, tariff sheet (Directive (EU) 2022/362 art. 11), p. {d['source']['page']}", "url": d["source"]["url"]},
        "sheets": f"(changes during {year} aren't followed: SAT's sheet gives its rates from 1 February {year}, and its +11.32% from 1 September {year} isn't applied)",
        "own": "Milan's ring roads (A50, A51, A52) at their barriers (it-barriers), not here; "})


if __name__ == "__main__":
    main(*sys.argv[1:])
