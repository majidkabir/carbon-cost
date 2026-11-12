"""Builds an ESTIMATE of Italy's motorway tolls (it-<date>.json) from
Autostrade per l'Italia's unit rates (fetch.py's it-aspi-tariffe.html).

Usage: python3 it.py fetched/ out-dir -> out-dir/it-<date>.json

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

MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
          "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}


def main(fetched, out):
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
    tb = {
        "country": "IT", "currency": "EUR", "valid_from": valid_from, "valid_to": f"{valid_from[:4]}-12-31",
        "name": "Italian motorway tolls (ESTIMATE: Autostrade per l'Italia's plain-stretch rate per km)",
        "law": "Estimate. Italian motorway tolls are each concession's unit rate per km, by vehicle class (A, B by height for two axles; 3, 4, 5 by axles) and by plain or mountain stretch, times the km between toll stations, plus 22% VAT, rounded to 10 cents (the concession agreements with the Ministry, under the State's laws and CIPE resolutions). "
               f"No station-to-station table can be fetched, so the route's km on toll motorways (OpenStreetMap ways tagged toll=yes) are priced at Autostrade per l'Italia's plain-stretch unit rate, VAT included, in force from {valid_from}: class B {pl[1]:.5f}, 3 {pl[2]:.5f}, 4 {pl[3]:.5f}, 5 {pl[4]:.5f} euro per km. "
               f"Mountain stretches cost about {up}% more on ASPI's network (class 5 {mo[4]:.5f}), other concessions have their own, mostly higher, rates, and the rounding and fixed-toll stretches aren't modelled, so the true toll can be higher.",
        "sources": [{"title": "Autostrade per l'Italia: come si calcola il pedaggio (unit rates per km, VAT included)", "url": "https://www.autostrade.it/it/servizi-al-cliente/pedaggio/come-si-calcola-il-pedaggio"}],
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
