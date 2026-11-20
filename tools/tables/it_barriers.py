"""Builds Italy's open-system barrier tolls (it-barriers-<date>.json), each
a fixed toll per passage at a barrier across the motorway:
- the Milan ring roads' barriers (Milano Serravalle - Milano Tangenziali:
  A50 Terrazzano, A51 Vimercate (the barrier at Agrate Brianza, A51 km
  19.5), A52 Sesto San Giovanni), from the operator's tables (fetch.py's
  it-mise-*.txt, PDFs as text);
- the A32 Torino-Bardonecchia's (SITAF: Avigliana, Salbertrand; the
  motorway's only toll stations, as it is an open system), from SITAF's
  tariffs page (it-sitaf-barriers.html);
- Autostrade per l'Italia's A8 Milano-Varese (Milano Nord, Gallarate Nord),
  A9 Lainate-Como (Como Grandate) and A12 Roma-Civitavecchia (Roma Ovest,
  Aurelia), Salerno Pompei Napoli's A3 (Napoli Sud, Nocera), and the
  Tangenziale di Torino's (Ivrea Torino Piacenza: Bruere, Falchera,
  Beinasco, Trofarello, and its Settimo Torinese toll, collected at the
  A5's Torino Nord barrier) and the A21's open Torino-Villanova stretch
  (collected at the Villanova barrier), from
  Autostrade per l'Italia's station-to-station toll form, read in Chrome
  (browser/it-aspi-barriers.txt: its toll service refuses scripted
  requests).
Each barrier is placed where Autostrade per l'Italia's station file
(it-aspi-caselli.json, its traffic site's caselli.json) puts its toll
point (the middle of its points, which must lie within 200 m); each must
be a barrier there (type BA). The open systems' ramp stations (Lainate, Gallarate, Fino
Mornasco, Maccarese, Torrimpietra, Civitavecchia Sud, the A3's thirteen,
Vadò) aren't modelled.

Usage: python3 it_barriers.py fetched/ out-dir -> out-dir/it-barriers-<date>.json

Prices: each Milan table's "Pedaggio all'utenza" (the toll the user pays,
VAT included, as the main Italian table's rates) of its latest year,
SITAF's "A32 Toll Tariffs (effective from <date>)" (VAT included: its
Avigliana amounts are SITAF's unit rate, ANAS fee and 22% VAT times the
barrier's 34.47 km) and the form's tolls (the capture's year; its
Avigliana must equal SITAF's page), classes B, 3, 4 and 5.
"""
import html, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m6toll  # noqa: E402

BARRIERS = [
    # (fetched table, name, motorway, network and station in ASPI's file)
    ("it-mise-terrazzano", "A50 Tangenziale Ovest di Milano, Terrazzano barrier", "A50", (8, 8)),
    ("it-mise-vimercate", "A51 Tangenziale Est di Milano, Vimercate barrier (Agrate Brianza)", "A51", (5, 1)),
    ("it-mise-sesto", "A52 Tangenziale Nord di Milano, Sesto San Giovanni barrier", "A52", (5, 659)),
]
CLASSES = ["A", "B", "3", "4", "5"]
# SITAF's barriers: (name on its page, name, network and station in ASPI's file).
SITAF = [
    ("Avigliana", "A32 Torino-Bardonecchia, Avigliana barrier", (24, 191)),
    ("Salbertrand", "A32 Torino-Bardonecchia, Salbertrand barrier", (24, 192)),
]
SITAF_PAGE = "https://www.sitaf.it/en/tariffs-and-passes-a32/"
# The barriers read from Autostrade per l'Italia's form: (network, station) -> name.
ASPI = {
    (8, 1): "A8 Milano-Varese, Milano Nord barrier",
    (8, 10): "A8 Milano-Varese, Gallarate Nord barrier",
    (8, 3): "A9 Lainate-Como, Como Grandate barrier",
    (9, 417): "Tangenziale di Torino (A55), Bruere barrier",
    (9, 418): "Tangenziale di Torino (A55), Falchera barrier",
    (9, 468): "Tangenziale di Torino (A55), Beinasco barrier",
    (9, 416): "Tangenziale di Torino (A55), Trofarello barrier",
    (12, 1): "A12 Roma-Civitavecchia, Roma Ovest barrier",
    (12, 3): "A12 Roma-Civitavecchia, Aurelia barrier",
    (6, 1): "A3 Napoli-Salerno, Napoli Sud barrier",
    (6, 11): "A3 Napoli-Salerno, Nocera barrier",
    (35, 308): "A12 Civitavecchia-Tarquinia, Tarquinia barrier",
}
# Tolls read from the form charged at another station's barrier: (tolls'
# network and station, the barrier's network and station, name). The
# Tangenziale di Torino's Settimo Torinese toll is collected at the A5's
# Torino Nord barrier (a closed system's barrier, type BC), where its toll
# points are; the A21's open Torino-Villanova stretch's (Villanova, network
# 34) at the A21's Villanova barrier.
AT = [((9, 419), (1, 401), "A5 Torino-Quincinetto, Torino Nord barrier (the Tangenziale di Torino's Settimo Torinese toll)"),
      ((34, 446), (1, 445), "A21 Torino-Piacenza, Villanova barrier (the open Torino-Villanova stretch's toll)")]
ASPI_FORM = "https://viabilita.autostrade.it/it/viabilita/traffico"
CAPTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser", "it-aspi-barriers.txt")
# Closed-system barriers whose toll to the next station is more than that
# station's km at the closed side's rate: (the barrier's network and
# station, the operator key the roads data gives the closed side, name).
# The barrier's toll point charges the difference by class: the form's
# toll (browser/it-aspi-closed-barriers.txt) less the two stations' km
# apart in the station file times the motorway table's rate for that key
# (it-<date>.json, built first); the free stretch on its other side isn't
# charged (tools/roads/build.py, UNTOLLED).
CLOSED = [
    ((1, 1), "Autostrade per l'Italia S.p.A.|A1", "A1 Milano-Napoli, Milano Sud barrier"),
    ((1, 201), "Milano Serravalle - Milano Tangenziali S.p.A.|A7", "A7 Milano-Serravalle, Milano Ovest barrier"),
    ((1, 443), "SATAP S.p.A.|A4|Novara Est-Milano", "A4 Torino-Milano, Milano Ghisolfa barrier"),
    ((1, 654), "Autostrade per l'Italia S.p.A.|A4", "A4 Milano-Brescia, Milano Est barrier"),
    ((1, 801), "Strada dei Parchi S.p.A.|A24", "A24 Roma-L'Aquila, Roma Est barrier"),
    ((1, 333), "Autostrade per l'Italia S.p.A.|A11", "A11 Firenze-Pisa, Firenze Ovest barrier"),
    ((1, 742), "Autostrade per l'Italia S.p.A.|A14", "A14 Bologna-Taranto, Taranto Nord barrier"),
    ((1, 521), "Autostrade per l'Italia S.p.A.|A27", "A27 Venezia-Belluno, Venezia barrier"),
    ((1, 780), "Autostrade per l'Italia S.p.A.|A16", "A16 Napoli-Canosa, Napoli Est barrier"),
    ((1, 783), "Autostrade per l'Italia S.p.A.|A30", "A30 Caserta-Salerno, Salerno barrier"),
    ((1, 681), "Autostrada del Brennero S.p.A.|A22|Brennero-Affi", "A22 Brennero-Modena, Brennero barrier"),
    ((1, 351), "Autostrada dei Fiori S.p.A.|A6", "A6 Torino-Savona, Barriera di Torino barrier"),
]
CLOSED_CAPTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser", "it-aspi-closed-barriers.txt")


def tolls(text, year=None):
    """The latest year's tolls to the user by class (or the given year's:
    the tables cover several); the year."""
    marks = [(int(m.group(1)), m.end()) for m in re.finditer(r"Tabella pedaggi 1\s*°\s*gennaio\s+(\d{4})", text, re.I)]
    if year:
        marks = [mk for mk in marks if mk[0] == year]
    if not marks:
        sys.exit(f"barrier table: no 'Tabella pedaggi 1° gennaio {year or '<year>'}'")
    year, at = max(marks)
    m = re.search(r"Pedaggio\s+all.{1,2}utenza\s+" + r"\s+".join([r"(\d+,\d\d)"] * 5), text[at:], re.I)
    if not m:
        sys.exit(f"barrier table {year}: no 'Pedaggio all'utenza' row")
    return {c: float(v.replace(",", ".")) for c, v in zip(CLASSES, m.groups())}, year


def sitaf_tolls(page):
    """SITAF's A32 barrier tolls by barrier and class; the year they're
    effective from (1 January)."""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " "))
    m = re.search(r"A32 Toll Tariffs \(effective from 01/01/(\d{4})\)", t)
    if not m:
        sys.exit("it-sitaf-barriers: no 'A32 Toll Tariffs (effective from 01/01/<year>)'")
    out = {b: {} for b, _, _ in SITAF}
    for c in CLASSES:
        r = re.search(rf"Class {c} Vehicles " + " ".join(rf"{b}: € (\d+\.\d\d)" for b, _, _ in SITAF), t[m.end():])
        if not r:
            sys.exit(f"it-sitaf-barriers: no class {c} tolls")
        for (b, _, _), v in zip(SITAF, r.groups()):
            out[b][c] = float(v)
    return out, int(m.group(1))


def capture(path=CAPTURE):
    """The form's tolls by (network, station) and class; the year read."""
    lines = open(path, encoding="utf-8").read().splitlines()
    m = next((re.search(r"read on (\d{4})-\d\d-\d\d", l) for l in lines if l.startswith("#") and "read on" in l), None)
    if not m:
        sys.exit("it-aspi-barriers: no 'read on <date>' line")
    out = {}
    for l in lines:
        r = re.fullmatch(r"(\d+) (\d+) \S+ (.+?) " + " ".join([r"(\d+(?:\.\d)?)"] * 5), l)
        if r:
            out[(int(r.group(1)), int(r.group(2)))] = (r.group(3), dict(zip(CLASSES, map(float, r.groups()[3:]))))
    return out, int(m.group(1))


def closed_capture(path=CLOSED_CAPTURE):
    """The form's barrier-to-station tolls: (network, station) -> (name,
    the arrival's (network, station), tolls by class); the year read."""
    lines = open(path, encoding="utf-8").read().splitlines()
    m = next((re.search(r"read on (\d{4})-\d\d-\d\d", l) for l in lines if l.startswith("#") and "read on" in l), None)
    if not m:
        sys.exit("it-aspi-closed-barriers: no 'read on <date>' line")
    out = {}
    for l in lines:
        r = re.fullmatch(r"(\d+) (\d+) \S+ (.+?) (\d+) (\d+) (.+?) " + " ".join([r"(\d+(?:\.\d)?)"] * 5), l)
        if r:
            out[(int(r.group(1)), int(r.group(2)))] = (r.group(3), (int(r.group(4)), int(r.group(5))), dict(zip(CLASSES, map(float, r.groups()[6:]))))
    return out, int(m.group(1))


def table_rate(rows, key, axles):
    """The motorway table's rate for an operator key and axle count, as the
    cost engine picks it: the key, then its first two parts, then its
    operator, then the default."""
    parts = key.split("|")
    for k in ["|".join(parts[:n]) for n in range(len(parts), 0, -1)] + [None]:
        for r in rows:
            if r.get("operator") == k and r.get("min_axles", 2) <= axles <= r.get("max_axles", 99):
                return r["rate"]
    sys.exit(f"it table: no rate for {key}, {axles} axles")


def closed_place(stations, key):
    """A closed-system barrier's toll point (type BC): of its toll points in
    ASPI's station file, the one nearest the station's own position."""
    x = stations.get(key)
    e = (x or {}).get("entrata") or {}
    ps = [(t["lon"], t["lat"]) for t in (x or {}).get("tollingIntersections", [])]
    if e.get("type") != "BC" or not ps:
        sys.exit(f"it-aspi-caselli: station {key} isn't a closed-system barrier with a toll point")
    p = min(ps, key=lambda q: m6toll.km(q, (e["lon"], e["lat"])))
    if m6toll.km(p, (e["lon"], e["lat"])) > 3:
        sys.exit(f"it-aspi-caselli: station {key}'s toll point is {m6toll.km(p, (e['lon'], e['lat'])):.1f} km from it")
    return p


def aspi_place(stations, key, types=("BA",)):
    """A barrier's toll point in ASPI's station file: a barrier (type BA,
    or the given types) whose toll points lie within 200 m, their middle."""
    x = stations.get(key)
    ps = [(t["lon"], t["lat"]) for t in (x or {}).get("tollingIntersections", [])]
    if not x or (x.get("entrata") or {}).get("type") not in types or not ps or max(m6toll.km(p, q) for p in ps for q in ps) > 0.2:
        sys.exit(f"it-aspi-caselli: station {key} isn't a barrier with one toll point")
    return sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)


def classes(t):
    return [{"min_kg": 3501, "min_axles": 5, "rate": t["5"]}, {"min_kg": 3501, "min_axles": 4, "rate": t["4"]},
            {"min_kg": 3501, "min_axles": 3, "rate": t["3"]}, {"min_kg": 3501, "rate": t["B"]}]


def main(fetched, out):
    stations = {(x["c_ret"], x["c_stz"]): x for x in json.load(open(os.path.join(fetched, "it-aspi-caselli.json"), encoding="utf-8"))["results"]}
    points, years, notes, a32, aspi = [], set(), [], [], []
    for fid, name, ref, key in BARRIERS:
        t, year = tolls(open(os.path.join(fetched, fid + ".txt"), encoding="utf-8").read())
        years.add(year)
        lon, lat = aspi_place(stations, key)
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(t)})
        notes.append(f"{name} class 5 EUR {t['5']:.2f}")
        print(name, t, round(lat, 6), round(lon, 6))
    st, year = sitaf_tolls(open(os.path.join(fetched, "it-sitaf-barriers.html"), encoding="utf-8", errors="replace").read())
    years.add(year)
    for b, name, key in SITAF:
        lon, lat = aspi_place(stations, key)
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(st[b])})
        a32.append(f"{b} class 5 EUR {st[b]['5']:.2f}")
        print(name, st[b], round(lat, 6), round(lon, 6))
    form, year = capture()
    years.add(year)
    if form.get(SITAF[0][2], ("", {}))[1] != st["Avigliana"]:
        sys.exit(f"it-aspi-barriers: Avigliana {form.get(SITAF[0][2])} isn't SITAF's {st['Avigliana']}")
    for key, name in ASPI.items():
        if key not in form:
            sys.exit(f"it-aspi-barriers: no tolls for {key} {name}")
        lon, lat = aspi_place(stations, key)
        t = form[key][1]
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(t)})
        aspi.append(f"{name.split(', ')[1].removesuffix(' barrier')} class 5 EUR {t['5']:.2f}")
        print(name, t, round(lat, 6), round(lon, 6))
    for key, at, name in AT:
        if key not in form:
            sys.exit(f"it-aspi-barriers: no tolls for {key} {name}")
        lon, lat = aspi_place(stations, at, ("BC",))
        t = form[key][1]
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(t)})
        aspi.append(f"{name.split(', ')[1]} class 5 EUR {t['5']:.2f}")
        print(name, t, round(lat, 6), round(lon, 6))
    cform, year = closed_capture()
    years.add(year)
    if len(years) != 1:
        sys.exit(f"barrier tables of different years {sorted(years)}")
    year = years.pop()
    rows = json.load(open(os.path.join(out, f"it-{year}-01-01.json"), encoding="utf-8"))["rows"]
    closed = []
    for key, op, name in CLOSED:
        if key not in cform:
            sys.exit(f"it-aspi-closed-barriers: no tolls for {key} {name}")
        _, to, t = cform[key]
        a, b = stations.get(key), stations.get(to)
        if not a or not b or a["c_ram"] != b["c_ram"]:
            sys.exit(f"it-aspi-caselli: {key} and {to} aren't on one road")
        km = abs(a["n_prg_km"] - b["n_prg_km"])
        extra = {c: round(t[c] - km * table_rate(rows, op, n), 2) for c, n in (("B", 2), ("3", 3), ("4", 4), ("5", 5))}
        if min(extra.values()) < 0:
            sys.exit(f"it-aspi-closed-barriers: {name}'s toll {t} is less than {km:.1f} km at {op}'s rates")
        lon, lat = closed_place(stations, key)
        points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes(extra)})
        closed.append(f"{name.split(', ')[1].removesuffix(' barrier')} class 5 EUR {extra['5']:.2f} (EUR {t['5']:.2f} to {b['description']}, {km:.1f} km on)")
        print(name, extra, round(km, 1), round(lat, 6), round(lon, 6))
    write(out, year, points, notes, a32, aspi, closed)


def write(out, year, points, notes, a32=(), aspi=(), closed=()):
    """The table: Milan's barriers (notes), and SITAF's (a32) and those read
    from Autostrade per l'Italia's form (aspi) where given (a past year's
    table has Milan's only)."""
    law = (f"A fixed toll to the user per passage by class (A, B by height for two axles; 3, 4, 5 by axles), VAT included, from 1 January {year}. "
           f"Milano Serravalle - Milano Tangenziali's tolls at the barriers of its semi-closed ring roads: "
           + "; ".join(notes) + ". The ring roads' other km carry no toll; the barrier tolls include Autostrade per l'Italia's share where the table gives one. ")
    sources = [{"title": f"Milano Serravalle: tariffe e pedaggi 2022-2026, {n}", "url": u} for n, u in (
        ("barriera di Terrazzano (A50)", "https://www.serravalle.it/uploads/pagine/Tariffe_e_pedaggi_2022_2026_Terrazzano_Tang_OVEST_MI2.pdf"),
        ("barriera di Vimercate (A51)", "https://www.serravalle.it/uploads/pagine/Tariffe_e_pedaggi_2022_2026_Vimercate_Tang_EST_MI6.pdf"),
        ("barriera di Sesto San Giovanni (A52)", "https://www.serravalle.it/uploads/pagine/Tariffe_e_pedaggi_2022_2026_Sesto_SG_Tang_NORD_MI1.pdf"))]
    name = "Italian open-system barriers: Milan ring roads"
    roads = "A50, A51 and A52 (Milan ring roads): the barriers of Terrazzano, Vimercate and Sesto San Giovanni"
    if a32:
        law += ("SITAF's tolls at the A32's two barriers, the open motorway's only toll stations (Avigliana for Rivoli-Susa, Salbertrand for Susa-Bardonecchia): "
                + "; ".join(a32) + " (Avigliana's are SITAF's unit rate per km, ANAS fee and 22% VAT times the barrier's 34.47 km, rounded to 10 cents). ")
        sources.append({"title": f"SITAF: A32 tariffs and passes (A32 toll tariffs effective from 01/01/{year})", "url": SITAF_PAGE})
        name += ", A32 Torino-Bardonecchia"
        roads += "; A32 Torino-Bardonecchia: the barriers of Avigliana and Salbertrand"
    if aspi:
        law += ("Autostrade per l'Italia's open A8 Milano-Varese, A9 Lainate-Como and A12 Roma-Civitavecchia, SAT's open A12 Civitavecchia-Tarquinia, Salerno Pompei Napoli's open A3 Napoli-Salerno and Ivrea Torino Piacenza's semi-closed Tangenziale di Torino (A55), the tolls Autostrade per l'Italia's station-to-station toll form gives for each barrier (read in a browser, as its service refuses scripted requests; it gives Avigliana's as SITAF does): "
                + "; ".join(aspi) + ". Their ramp stations (Lainate, Gallarate, Fino Mornasco, Maccarese, Torrimpietra, Civitavecchia Sud, the A3's thirteen from Ponticelli to Cava de' Tirreni, Vadò) aren't modelled; the Tangenziale's Settimo Torinese toll is collected at the A5's Torino Nord barrier, where it's charged (Ivrea Torino Piacenza's toll calculator gives Torino Nord-Settimo Nord as that toll), and the A21's open Torino-Villanova stretch's at the A21's Villanova barrier (its calculator charges Villanova B.-Asti Ovest as that toll and the km; OSM tags the stretch's own km toll-free). ")
        sources.append({"title": "Autostrade per l'Italia: Info viabilità, Calcola il pedaggio da casello a casello (read in a browser; tools/tables/browser/it-aspi-barriers.txt)", "url": ASPI_FORM})
        name += ", A8 Milano-Varese, A9 Lainate-Como, A12 Roma-Civitavecchia and Civitavecchia-Tarquinia, A3 Napoli-Salerno, Tangenziale di Torino"
        roads += "; A8 Milano-Varese: Milano Nord and Gallarate Nord; A9 Lainate-Como: Como Grandate; A12 Roma-Civitavecchia: Roma Ovest and Aurelia; A12 Civitavecchia-Tarquinia (SAT): Tarquinia; A3 Napoli-Salerno: Napoli Sud and Nocera; Tangenziale di Torino (A55): Bruere, Falchera, Beinasco and Trofarello, and its Settimo Torinese toll at the A5's Torino Nord barrier; A21 Torino-Villanova: its toll at the Villanova barrier"
    if closed:
        law += ("Closed-system barriers whose toll is more than the km to the next station at the motorway's rate: each charges a fixed toll for the free stretch on its other side and more, so its toll point charges the form's toll to the next station less the two stations' km apart (in Autostrade per l'Italia's station file) at the rate the motorway table gives that stretch, and the free stretch isn't charged by the km: "
                + "; ".join(closed) + ". The form's tolls are rounded to 10 cents, so these are within 5 cents. ")
        sources.append({"title": "Autostrade per l'Italia: Info viabilità, Calcola il pedaggio da casello a casello, closed-system barriers (read in a browser; tools/tables/browser/it-aspi-closed-barriers.txt)", "url": ASPI_FORM})
        name += ", closed-system barriers (Milan, Turin, Rome, Naples, Florence, Taranto, Salerno, Venice, Brennero)"
        roads += "; closed-system barriers: " + ", ".join(c.split(" class ")[0] for c in closed)
    law += "Each barrier is placed at the toll point Autostrade per l'Italia's station file gives it (Milano Serravalle's Vimercate barrier is the A51's toll gate at Agrate Brianza, km 19.5)."
    sources.append({"title": "Autostrade per l'Italia: Info viabilità's station file (toll stations, their network, road and toll point)", "url": "https://viabilita.autostrade.it/json/caselli.json"})
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31", "crossings": True,
        "name": name, "law": law, "sources": sources,
        "vehicles": "Classes B (two axles), 3, 4 and 5 (five axles or more)", "min_kg": 3501,
        "tolled_roads": roads + ".",
        "point_match_km": 0.1, "toll_points": points, "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"it-barriers-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
