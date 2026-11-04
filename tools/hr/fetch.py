"""Fetches Hrvatske autoceste's toll price lists (hac.hr/en/toll/toll-rates)
into hr-prices.json: for each road page, the price in EUR including VAT
from every entry to every exit, by vehicle group (IA, I, II, III, IV),
and the OpenStreetMap toll booths of Croatia (hr-booths.json from
osmium) matched to the station names.

Usage: python3 fetch.py hr-booths.geojsonseq out-dir
"""
import html, json, re, sys, time, urllib.parse, urllib.request

BASE = "https://www.hac.hr/en/toll/toll-rates/"
PAGES = ["a1", "a2", "a3", "a4", "a11", "bregana", "rupa"]
UA = {"User-Agent": "carbon-cost docs fetch"}


def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print("retry", url, e, file=sys.stderr)
            time.sleep(3)
    raise RuntimeError(url)


def eur(s):
    s = s.replace("€", "").replace("\xa0", "").strip().replace(".", "").replace(",", ".")
    return float(s) if s else None


def parse(page):
    entry = re.search(r"(?:Entry|Ulaz):\s*([^<]+)<", page)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        cells = [re.sub(r"\s+", " ", c) for c in cells]
        if len(cells) >= 6 and "€" in cells[-1]:
            rows.append([cells[0]] + [eur(c) for c in cells[-5:]])
    links = sorted(set(html.unescape(u) for u in re.findall(r'href="([^"]*\?entry=[^"]+)"', page)))
    return (html.unescape(entry.group(1)).strip() if entry else None), rows, links


def main(booths_path, out):
    data = {}
    for p in PAGES:
        first = get(BASE + p)
        entry0, rows0, links = parse(first)
        entries = {entry0: rows0}
        for l in links:
            name = urllib.parse.unquote(l.split("entry=", 1)[1]).replace("+", " ")
            if name in entries:
                continue
            url = l if l.startswith("http") else urllib.parse.urljoin(BASE + p, l)
            e, rows, _ = parse(get(url))
            entries[e or name] = rows
            time.sleep(0.3)
        data[p] = entries
        print(p, len(entries), "entries", sum(len(v) for v in entries.values()), "prices")
    json.dump(data, open(out + "/hr-prices.json", "w"), ensure_ascii=False, indent=0)
    names = sorted({n for es in data.values() for e, rows in es.items() for n in [e] + [r[0] for r in rows] if n})
    booths = []
    for line in open(booths_path, encoding="utf-8"):
        f = json.loads(line.lstrip("\x1e"))
        if f["geometry"]["type"] != "Point":
            continue
        t = f["properties"]
        booths.append({"name": t.get("name", ""), "kind": t.get("barrier") or t.get("highway"), "op": t.get("operator", ""), "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]})
    json.dump({"stations": names, "booths": booths}, open(out + "/hr-booths.json", "w"), ensure_ascii=False, indent=0)
    print(len(names), "station names,", len(booths), "booths/junctions in OSM")


if __name__ == "__main__":
    main(*sys.argv[1:])
