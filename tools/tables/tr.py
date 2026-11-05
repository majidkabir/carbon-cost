"""Builds the Turkish bridge toll table from the General Directorate of
Highways' (Karayolları Genel Müdürlüğü, KGM) 2026 tariffs (fetch.py's
tr-1-15temmuz-fsm, tr-2-osmangazi, tr-3-ysskoprusu, tr-4-1915canakkale
.pdf, as pdftotext -layout text) and the bridges in OpenStreetMap (the
workflow's tr-osm.geojsonseq, from Geofabrik's Turkey extract; its date
in tr-osm-timestamp.txt).

Usage: python3 tr.py fetched/ out-dir -> out-dir/tr-<date>.json

KGM classes vehicles by axles: 1 two axles under 3.20 m wheelbase, 2 two
axles of 3.20 m or more, 3 three axles, 4 four and five axles, 5 six or
more ("4 VE 5 AKSLI HER TÜRLÜ ARAÇLAR"). Each tariff lists the price
per passage by class, "KDV dahil" (including VAT); prices are divided by
1.20, Turkey's general VAT rate (KDV Kanunu 28. madde, 20% since
2023-07-10). A two-axle truck is taken as class 2. The 15 Temmuz Şehitler
and Fatih Sultan Mehmet bridges have one tariff, the first price column
("KÖPRÜ GEÇİŞ ÜCRETİ"). The bridges charge both ways (the tariffs say so
for 15 Temmuz, FSM and Yavuz Sultan Selim since 2022; Osmangazi and 1915
Çanakkale charge at a toll station for either direction).

Each bridge is placed at the middle of its longest OSM way (the main
span) named after it, one point per carriageway; a route crossing the
bridge passes there. The table is valid from the latest date the
tariffs give ("01/07/2026 saat 00:00'dan itibaren geçerlidir").
"""
import json, math, os, re, sys

BRIDGES = [("tr-1-15temmuz-fsm", ["15 Temmuz Şehitler Köprüsü", "Fatih Sultan Mehmet Köprüsü"]),
           ("tr-2-osmangazi", ["Osmangazi Köprüsü"]),
           ("tr-3-ysskoprusu", ["Yavuz Sultan Selim Köprüsü"]),
           ("tr-4-1915canakkale", ["1915 Çanakkale Köprüsü"])]
KDV = 1.20
# KGM class -> axle bounds of the truck classes.
AXLES = {2: (2, 2), 3: (3, 3), 4: (4, 5), 5: (6, 0)}


def tl(s):
    return float(s.replace(".", "").replace(",", "."))


def tariff(path):
    t = open(path, encoding="utf-8").read().replace("​", "")
    m = re.search(r"\((\d\d)/(\d\d)/(\d{4}) [Ss]aat 00:00'dan itibaren geçerlidir\.\)", t)
    if not m:
        sys.exit(f"{path}: no date")
    date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    prices = {}
    for line in t.split("\n"):
        m = re.match(r"^\s*([1-6])\s+(?:.*?\s)?(\d{1,3}(?:\.\d{3})*,\d\d)(?:\s*₺)?(?:\s+[\d,]+)?\s*$", line)
        if m and int(m.group(1)) not in prices:
            prices[int(m.group(1))] = tl(m.group(2))
    if sorted(prices) != [1, 2, 3, 4, 5, 6]:
        sys.exit(f"{path}: classes {prices}")
    return date, prices


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def middle(coords):
    """The point halfway along a line, and the line's length in km."""
    total = sum(km(coords[i], coords[i + 1]) for i in range(len(coords) - 1))
    left = total / 2
    for i in range(len(coords) - 1):
        d = km(coords[i], coords[i + 1])
        if d >= left and d > 0:
            f = left / d
            return [coords[i][0] + f * (coords[i + 1][0] - coords[i][0]), coords[i][1] + f * (coords[i + 1][1] - coords[i][1])], total
        left -= d
    return coords[0], total


def main(fetched, out):
    ways = {}
    for line in open(os.path.join(fetched, "tr-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if g["type"] != "LineString" or p.get("highway") not in ("motorway", "trunk", "primary"):
            continue
        for k in ("name", "bridge:name"):
            if p.get(k):
                ways.setdefault(p[k], []).append((p, g["coordinates"]))
    date, points = "", []
    for sid, names in BRIDGES:
        d, prices = tariff(os.path.join(fetched, sid + ".txt"))
        date = max(date, d)
        classes = [{"min_axles": lo, **({"max_axles": hi} if hi else {}), "rate": round(prices[c] / KDV, 4)} for c, (lo, hi) in AXLES.items()]
        for name in names:
            ws = ways.get(name, [])
            if not ws:
                sys.exit(f"{name}: no way in OpenStreetMap")
            mids = sorted((middle(c) for _, c in ws), key=lambda x: -x[1])
            longest = mids[0][1]
            # The main span of each carriageway: the longest ways (within 10%).
            keep = []
            for (lon, lat), length in mids:
                if length >= 0.9 * longest and all(km((lon, lat), k) > 0.01 for k in keep):
                    keep.append((lon, lat))
            if len(keep) > 2 or (len(keep) == 2 and km(keep[0], keep[1]) > 0.2):
                sys.exit(f"{name}: main spans {keep}")
            for lon, lat in keep:
                points.append({"name": name, "lat": round(lat, 6), "lon": round(lon, 6), "rate": 0, "classes": classes})
            print(f"{name}: {len(ws)} ways, main span {longest:.2f} km, {len(keep)} points; class 2-5 TL {[prices[c] for c in AXLES]} ({d})")
    osm = open(os.path.join(fetched, "tr-osm-timestamp.txt")).read().strip()[:10]
    tb = {
        "country": "TR", "currency": "TRY", "valid_from": date,
        "name": "Turkish bridge tolls (KGM)",
        "law": "Karayollarında Geçiş Ücretlerinin Belirlenmesi ve Uygulanmasına Dair Yönetmelik; KGM's 2026 tariffs of the 15 Temmuz Şehitler, Fatih Sultan Mehmet, Osmangazi, Yavuz Sultan Selim and 1915 Çanakkale bridges. Per passage, either direction, by KGM class: 2 (two axles of 3.20 m or more wheelbase), 3 (three axles), 4 (four and five axles), 5 (six or more), excluding 20% KDV (VAT). Trucks may not use 15 Temmuz Şehitler or FSM (UKOME decision) but pay their tariff if they do. Each bridge placed at its main span in OpenStreetMap (extract of " + osm + "). The KGM and concession motorways' entry–exit tolls aren't included.",
        "sources": [{"title": "KGM: Otoyol ve Köprü Geçiş Ücretleri", "url": "https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Otoyollar/UcretlerYeni.aspx"},
                    {"title": "KGM: 15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri Geçiş Ücretleri Tarifesi", "url": "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/1-15Temmuz-FSM.pdf"},
                    {"title": "KGM: Osmangazi Köprüsü Geçiş Ücretleri Tarifesi", "url": "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/2-Osmangazi.pdf"},
                    {"title": "KGM: Yavuz Sultan Selim Köprüsü Geçiş Ücretleri Tarifesi", "url": "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/3-YSSKoprusu.pdf"},
                    {"title": "KGM: 1915 Çanakkale Köprüsü Geçiş Ücretleri Tarifesi", "url": "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/4-1915Canakkale.pdf"},
                    {"title": "OpenStreetMap (Geofabrik extract), bridges", "url": "https://download.geofabrik.de/europe/turkey.html"}],
        "vehicles": "Trucks of two or more axles (KGM classes 2 to 5)",
        "tolled_roads": "15 Temmuz Şehitler and Fatih Sultan Mehmet bridges (Bosphorus), Yavuz Sultan Selim bridge (Bosphorus, O-7), Osmangazi bridge (İzmit Gulf, O-5), 1915 Çanakkale bridge (Dardanelles, O-6).",
        "point_match_km": 0.05,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"tr-{date}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
