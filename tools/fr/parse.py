"""Parses the tariff documents listed in documents.json (from fetch.py's
output folder) into pairs.csv: one row per document, entry and exit
station, with the tariff distance and the class 3 and class 4 prices in
EUR including VAT, and the date the document says they apply from.

Usage: python3 parse.py documents.json fetched/ pairs.csv

Parsers (text documents, from pdftotext -layout):
  list        ENTRY  EXIT  km  c1 €  c2 €  c3 €  c4 €  c5 €
  list_codes  code ENTRY  code EXIT  km  c1 €  c2 €  c3 €  c4 €  c5 € [km]
  list_roads  road exit-no ENTRY  road exit-no EXIT  c1 €  c2 €  c3 €  c4 €  c5 €
and for PDFs:
  grid        VINCI Autoroutes' class grids (grid.py); each page says which
              class it prices ("CLASSE 3"). A document may be one PDF per
              class ("files"): the class 3 file's URL and sha256 go in url and
              sha256, the class 4 file's in url4 and sha256_4.
"""
import csv, json, os, re, sys, unicodedata
from collections import Counter

PRICES = r"\s+".join(f"(?P<c{i}>[\\d ]+,\\d\\d) €" for i in range(1, 6))
PARSERS = {
    "list": re.compile(r"^\s*(?P<entry>\S.*?)\s{2,}(?P<exit>\S.*?)\s{2,}(?P<km>[\d ]+,\d+)\s+" + PRICES),
    "list_codes": re.compile(r"^\s*\d+\s+(?P<entry>\S.*?)\s{2,}\d+\s+(?P<exit>\S.*?)\s{2,}(?P<km>[\d ]+,\d+)\s+" + PRICES),
    "list_roads": re.compile(r"^\s*A\d+\s+(?:\d+(?:\.\d+)?[a-z]?|-)\s+(?P<entry>\S.*?)\s{2,}A\d+\s+(?:\d+(?:\.\d+)?[a-z]?|-)\s+(?P<exit>\S.*?)\s{2,}" + PRICES),
}
MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def valid_from(text):
    m = re.search(r"(?:en vigueur|applicables?|TTC) (?:au|à compter du) (\d+)(?:er)? (\w+) (\d{4})", text, re.I)
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" if m else ""


def key(name):
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()


def grid_rows(d, fetched, manifest):
    """Yields (url, sha256, url4, sha256_4, valid_from, entry, exit, class3, class4)
    for a grid document. A station spelled two ways in the document
    ("Pamiers Nord", "Pamiers nord") gets its most frequent spelling."""
    import pymupdf
    import grid
    prices, src, spell, vf = {3: {}, 4: {}}, {}, Counter(), ""
    for f in d.get("files", [d.get("file")]):
        doc = pymupdf.open(os.path.join(fetched, f))
        for page in doc:
            text = page.get_text()
            m = re.search(r"CLASSE\s+(\d)", text)
            if not m or int(m.group(1)) not in prices:
                continue
            vf = vf or valid_from(text)
            src[int(m.group(1))] = manifest[f]
            for a, b, p in grid.page_pairs(page):
                spell.update([a, b])
                prices[int(m.group(1))].setdefault(tuple(sorted((a, b))), p)
    best = {}
    for n, c in spell.most_common():
        best.setdefault(key(n), n)
    s3, s4 = src[3], src[4]
    same = s3["url"] == s4["url"]
    out = {}
    for (a, b), p3 in prices[3].items():
        p4 = prices[4].get((a, b))
        if p4 is not None:
            out.setdefault((best[key(a)], best[key(b)]), (p3, p4))
    for (a, b), (p3, p4) in out.items():
        yield s3["url"], s3["sha256"], "" if same else s4["url"], "" if same else s4["sha256"], vf, a, b, p3, p4
    print(f"{d['operator']}: {len(prices[3])} class 3 and {len(prices[4])} class 4 grid cells, {len(out)} pairs, valid from {vf}")


def main(docs_path, fetched, out):
    docs = json.load(open(docs_path, encoding="utf-8"))["documents"]
    manifest = {f["file"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    with open(out, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["operator", "document", "url", "sha256", "url4", "sha256_4", "valid_from", "entry", "exit", "km", "class3", "class4"])
        for d in docs:
            if d["parser"] == "grid":
                for url, sha, url4, sha4, vf, a, b, p3, p4 in grid_rows(d, fetched, manifest):
                    w.writerow([d["operator"], d.get("files", [d.get("file")])[0], url, sha, url4, sha4, vf, a, b, "", p3, p4])
                continue
            text = open(os.path.join(fetched, d["file"]), encoding="utf-8").read()
            src = manifest[d["url_from"]]
            vf, n = valid_from(text), 0
            for line in text.splitlines():
                m = PARSERS[d["parser"]].match(line)
                if m:
                    km = num(m["km"]) if "km" in m.groupdict() else ""
                    w.writerow([d["operator"], d["url_from"], src["url"], src["sha256"], "", "", vf, m["entry"].strip(), m["exit"].strip(),
                                km, num(m["c3"]), num(m["c4"])])
                    n += 1
            lines = text.count(" €") // 5
            print(f"{d['file']}: {n} pairs (about {lines} price rows in the text), valid from {vf}")


if __name__ == "__main__":
    main(*sys.argv[1:])
