"""Builds the Hungarian HU-GO rate table and its section list from the
Nemzeti Jogszabálytár's consolidated text of 25/2013. (V. 31.) NFM
rendelet, as fetch.py saved it (hu-25-2013.html and its parts
hu-25-2013-block-*.html).

Usage: python3 hu.py fetched/ out-dir -> out-dir/hu-<date>.json and
out-dir/hu-annex1.json (the section list tools/roads/build.py reads)

Read from the text: § 1 (2)-(4a), the infrastructure charge in HUF/km
including 27% VAT for J2-J5 on expressways (gyorsforgalmi út) and main
roads (főút); annex 1, the tolled elementary sections (road, ED ID,
start and end chainage, length in m, level, suburban share); annex 2,
the external-cost charge in eurocent/km excluding VAT (air and noise by
EURO class on suburban and interurban roads; CO2 by EURO class, low-
and zero-emission). The table's date is the text's state ("2026.07.01.").
"""
import glob, html, json, os, re, sys


def cells(tr):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]


def num(s):
    return float(s.replace(",", "."))


def parse(fetched):
    page = open(os.path.join(fetched, "hu-25-2013.html"), encoding="utf-8").read()
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    state = re.search(r"az útdíjköteles utakról (\d{4})\.(\d\d)\.(\d\d)\.", text)
    infra = {}
    for cat in ("J2", "J3", "J4", "J5"):
        m = re.search(cat + r" díjkategóriába tartozó útdíjköteles gépjármű kilométerenkénti, általános forgalmi adót magában foglaló "
                      r"infrastruktúradíjának alapmértéke: a\) gyorsforgalmi úton ([\d,]+) forint, b\) főúton ([\d,]+) forint", text)
        infra[cat] = (num(m.group(1)), num(m.group(2)))
    blocks = "".join(open(f, encoding="utf-8").read() for f in sorted(glob.glob(os.path.join(fetched, "hu-25-2013-block-*.html"))))
    a2 = blocks.index("2. melléklet a 25/2013")
    seg = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", blocks[:a2], re.S):
        c = cells(tr)
        if len(c) == 8 and re.fullmatch(r"\d+", c[0]) and re.fullmatch(r"\d+", c[5]):
            seg.append({"n": int(c[0]), "road": c[1], "id": c[2], "start": c[3].replace(" ", ""), "end": c[4].replace(" ", ""),
                        "m": int(c[5]), "level": {"gyorsforgalmi": "motorway", "főúti": "main"}[c[6]], "f": num(c[7])})
    part2 = blocks[a2:]
    at = part2.index("szén-dioxid")
    an, co2 = {}, {}
    for table, out, width in ((part2[:at], an, 4), (part2[at:], co2, 3)):
        cat = None
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            c = cells(tr)
            if len(c) == width + 1 and re.fullmatch(r"J\d", c[1]):
                cat, c = c[1], [c[0]] + c[2:]
            if cat and len(c) == width and re.match(r"\d+\.$", c[0]) and re.fullmatch(r"[\d,]+", c[2]):
                out.setdefault(cat, []).append(tuple(num(v) for v in c[2:]))
    # Air and noise: Euro 0, I, ..., VI, then cleaner than Euro VI.
    an = {k: v for k, v in an.items()}
    # CO2: Euro 0, Euro I-VI (J2) or I-III and IV-VI, low-emission, zero-emission.
    co2 = {k: (v[0][0], v[1][0], v[1][0], v[2][0]) if len(v) == 4 else (v[0][0], v[1][0], v[2][0], v[3][0]) for k, v in co2.items()}
    assert len(an) == 4 and all(len(v) == 8 for v in an.values()) and len(co2) == 4, (an, co2)
    return f"{state.group(1)}-{state.group(2)}-{state.group(3)}", infra, seg, an, co2


def main(fetched, outdir, law=None, sources=None):
    valid_from, infra, seg, an, co2 = parse(fetched)
    fbar = {}
    for lv in ('motorway', 'main'):
        s = [r for r in seg if r['level'] == lv]
        fbar[lv] = sum(r['m'] * r['f'] for r in s) / sum(r['m'] for r in s)
    EUR_HUF = 388.6
    VAT = 1.27
    axles = {'J2': dict(max_axles=2), 'J3': dict(min_axles=3, max_axles=3), 'J4': dict(min_axles=4, max_axles=4), 'J5': dict(min_axles=5)}
    huf = lambda c: round(c / 100 * EUR_HUF, 2)
    rows = []
    def row(comp, cat, rate, road=None, **f):
        r = {'component': comp}
        if road: r['road'] = road
        r.update(axles[cat]); r.update(f); r['rate'] = round(rate, 4); rows.append(r)
    for cat in ('J2', 'J3', 'J4', 'J5'):
        mw, mr = infra[cat]
        row('infrastructure', cat, mw / VAT, 'motorway')
        row('infrastructure', cat, mr / VAT, 'other')
        for area, i in (('suburban', 0), ('interurban', 1)):
            row('air_noise', cat, huf(an[cat][7][i]), area=area, co2_class=[4, 5])
            for e in range(7):
                row('air_noise', cat, huf(an[cat][e][i]), area=area, euro=[e])
        c = co2[cat]
        row('co2', cat, 0, co2_class=[5])
        row('co2', cat, huf(c[3]), co2_class=[4])
        row('co2', cat, huf(c[0]), euro=[0])
        row('co2', cat, huf(c[1]), euro=[1, 2, 3])
        row('co2', cat, huf(c[2]), euro=[4, 5, 6])
    # check against HU-GO gross table 2025 (same EUR/HUF rate): J2 E0 suburban 91.80, interurban 48.86, CO2 22.21
    assert round(huf(18.6) * VAT, 2) == 91.80 and round(huf(9.9) * VAT, 2) == 48.86 and round(huf(4.5) * VAT, 2) == 22.21
    assert round(huf(3.4) * VAT, 2) == 16.78 and round(huf(2.8) * VAT, 2) == 13.82 and round(huf(0.8) * VAT, 2) == 3.95 and round(huf(4.0) * VAT, 2) == 19.74
    t = {
     "country": "HU", "currency": "HUF", "valid_from": valid_from, "valid_to": valid_from[:4] + "-12-31",
     "name": "Hungarian distance-based toll (HU-GO)",
     "law": ("25/2013. (V. 31.) NFM rendelet (in force from 1 July 2026): § 1 (2)-(4a) as set by 46/2025. (XII. 23.) ÉKM gives the infrastructure charge in HUF/km including 27% VAT by category "
             "(J2-J5 by axles, 209/2013. (VI. 18.) Korm. rendelet § 2) and road level (expressway or main road); annex 2 gives the external-cost charge in eurocent/km excluding VAT "
             "(air and noise for suburban and interurban roads by EURO class, CO2 by EURO class, low- and zero-emission); annex 1 as set by 34/2025. (XI. 30.) ÉKM lists the 2,639 tolled elementary sections with their level and suburban share. "
             "Rates here exclude VAT: the infrastructure charge is divided by 1.27; the external-cost charge is converted at 388.60 HUF/EUR (ECB rate of 2 October 2023, kept because later 1 October rates moved it by 5% or less, 209/2013 § 3/A (2)-(3)), rounded to 0.01 HUF."),
     "sources": [
      {"title": "25/2013. (V. 31.) NFM rendelet (Nemzeti Jogszabálytár, in force from 1 July 2026)", "url": "https://njt.jog.gov.hu/jogszabaly/2013-25-20-2W"},
      {"title": "Magyar Közlöny 2025/143: 34/2025. (XI. 30.) ÉKM rendelet, annex 1 (tolled sections from 1 July 2026)", "url": "https://magyarkozlony.hu/dokumentumok/ffc3529aaa9c6075ef082089b3ec049444bc554a/letoltes"},
      {"title": "46/2025. (XII. 23.) ÉKM rendelet (its March 2026 step did not enter into force, 2/2026. (II. 26.) ÉKM 3. §)", "url": "https://njt.jog.gov.hu/jogszabaly/2025-46-20-8X"},
      {"title": "209/2013. (VI. 18.) Korm. rendelet § 3/A (EUR/HUF conversion)", "url": "https://njt.jog.gov.hu/jogszabaly/2013-209-20-22"},
      {"title": "HU-GO toll rate table (gross HUF/km, same EUR/HUF rate)", "url": "https://hu-go.hu/articles/article/e-tolls-the-table-of-toll-rates-applicable-from-january-is-now-available"}
     ],
     "vehicles": "Vehicles over 3.5 t maximum authorised mass (buses have their own rates)",
     "min_kg": 3501,
     "tolled_roads": ("Expressways (%.0f km) and main roads (%.0f km) listed in annex 1. Km on other roads are priced at the main-road rate. The air and noise charge has suburban and interurban rates; each route km takes its section's suburban share from annex 1 where OpenStreetMap places the section, else the network share (%.1f%% on expressways, %.1f%% on main roads). Low-emission means CO2 class 4."
                      % (sum(r['m'] for r in seg if r['level']=='motorway')/1000, sum(r['m'] for r in seg if r['level']=='main')/1000, fbar['motorway']*100, fbar['main']*100)),
     "motorway_share": 1,
     "suburban_share": {"motorway": round(fbar['motorway'], 4), "other": round(fbar['main'], 4)},
     "rows": rows,
    }
    # A past time state (tools/history/build_hu.py) names its own text.
    if law:
        t["law"] = law + t["law"][t["law"].index(" Rates here exclude VAT"):]
    if sources:
        t["sources"] = sources + t["sources"][3:]
    os.makedirs(outdir, exist_ok=True)
    json.dump(t, open(os.path.join(outdir, f'hu-{valid_from}.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(seg, open(os.path.join(outdir, 'hu-annex1.json'), 'w'), ensure_ascii=False)
    print(len(rows), 'rows,', len(seg), 'sections, valid from', valid_from)


if __name__ == "__main__":
    main(*sys.argv[1:])
