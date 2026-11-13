"""Builds Gipuzkoa's canon for heavy vehicles on the N-I and A-15 (Bidegi)
as a closed system priced by entry and exit.

Usage: python3 es_basque.py fetched/ out-dir -> out-dir/es-basque-<date>.json

Law: Norma Foral 5/2021, de 3 de diciembre (Gipuzkoa), consolidated from
27 December 2022 (fetch.py's es-gipuzkoa-nf-5-2021): the canon is charged
on the N-I and A-15 along their whole length in Gipuzkoa by free-flow
gantries (article 6), to heavy goods vehicles over 3.5 t: "Pesados 1"
under 12 t and "Pesados 2" from 12 t (article 7), VAT included, at a
percentage of the amounts by EURO class (article 8: 80% EURO 6, 85% EURO 5,
for trucks registered with Bidegi with a TAG; 75% for electric, hybrid and
gas trucks, not modelled), with frequency discounts from the 21st trip in
a month (article 8 bis, not modelled).

Prices: Bidegi's 2026 tariff matrix (fetch.py's es-bidegi-n1-a15-2026,
pdftotext -bbox words): page 1 Pesados 1, page 2 Pesados 2; rows are
entries ("Sarrera"), columns exits ("Irteera"), numbered 1 to 32 with
their road and PK. Prices exclude the 21% VAT here.

Stations: fetch.py's es-basque-osm.json (Overpass): the N-I and A-15
carriageways and their junction nodes, matched to the matrix's stations
by exit number (the PK rounded); see place().
"""
import json, math, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_matrix  # noqa: E402  (pdftotext -bbox words)

VAT = 1.21
PRICE = re.compile(r"^\d+,\d\d$")


def matrix(path):
    """{group: {(entry, exit): euros with VAT}}, {station: (road, pk)}."""
    out, roads = {}, {}
    for ws in tr_matrix.words(path):
        title = " ".join(w[4] for w in ws if w[1] < 100)
        m = re.search(r"Pesados (\d)", title)
        hdr = [w for w in ws if w[4] == "Zk"]
        if not m or not hdr:
            continue
        y0 = (hdr[0][1] + hdr[0][3]) / 2
        cols = {int(w[4]): (w[0] + w[2]) / 2 for w in ws if abs((w[1] + w[3]) / 2 - y0) < 2 and w[4].isdigit() and w[0] > hdr[0][2]}
        rows = {}
        for w in ws:
            y = (w[1] + w[3]) / 2
            if y > y0 + 5 and hdr[0][0] - 5 < w[0] < hdr[0][2] + 10 and w[4].isdigit() and int(w[4]) <= max(cols):
                rows.setdefault(int(w[4]), y)
        for r, y in rows.items():
            line = sorted((w for w in ws if abs((w[1] + w[3]) / 2 - y) < 2 and w[2] < hdr[0][0]), key=lambda w: w[0])
            road = next((w[4] for w in line if re.fullmatch(r"N-I|A-15", w[4])), None)
            pk = next((float(w[4].replace(",", ".")) for w in line if re.fullmatch(r"\d{3},\d\d", w[4])), None)
            if road and pk:
                roads[r] = (road, pk)
        g = out.setdefault(f"P{m.group(1)}", {})
        for w in ws:
            if not PRICE.match(w[4]) or w[0] < hdr[0][2] or w[1] < y0 + 5:
                continue
            y, x = (w[1] + w[3]) / 2, (w[0] + w[2]) / 2
            r = [k for k, v in rows.items() if abs(v - y) < 2]
            c = min(cols, key=lambda k: abs(cols[k] - x))
            if not r or abs(cols[c] - x) > 12:
                sys.exit(f"N-I/A-15: price {w[4]} at ({x:.0f}, {y:.0f}) is in no row or column")
            g[(r[0], c)] = float(w[4].replace(",", "."))
    if sorted(out) != ["P1", "P2"] or len(roads) != 32:
        sys.exit(f"N-I/A-15: groups {sorted(out)}, {len(roads)} stations")
    if set(out["P1"]) != set(out["P2"]):
        sys.exit("N-I/A-15: Pesados 1 and 2 price different pairs")
    for (a, b), v in out["P1"].items():
        if out["P2"][a, b] < v:
            sys.exit(f"N-I/A-15: {a}-{b} is cheaper for Pesados 2")
    return out, roads
