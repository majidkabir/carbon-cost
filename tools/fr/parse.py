"""Parses the tariff documents listed in documents.json (from fetch.py's
output folder) into pairs.csv: one row per document, entry and exit
station, with the tariff distance and the class 3 and class 4 prices in
EUR including VAT, the date the document says they apply from, and the
stations' exit numbers where the document gives them.

Usage: python3 parse.py documents.json fetched/ pairs.csv

Parsers (text documents, from pdftotext -layout):
  list        ENTRY  EXIT  km  c1 €  c2 €  c3 €  c4 €  c5 €
  list_codes  code ENTRY  code EXIT  km  c1 €  c2 €  c3 €  c4 €  c5 € [km]
  list_roads  road exit-no ENTRY  road exit-no EXIT  c1 €  c2 €  c3 €  c4 €  c5 €
  gares       one page per entry station ("Gare de X"), then rows
              "code EXIT c1 c2 c3 c4 c5" (A'liénor)
  columns     small tables on a web page, configured in documents.json
              (headings to check, and what each column prices) (ATMB)
  barrier     a single barrier priced alone: its first five rows of two
              prices are classes 1 to 5 (Millau)
text positions saved from a browser (the Sanef site refuses scripted
downloads; sanef/extract.js, sanef.py):
  items       Sanef's and SAPN's triangles; the file's header gives the
              PDF's URL and sha256
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
    "list_roads": re.compile(r"^\s*A\d+\s+(?P<entry_no>\d+(?:\.\d+)?[a-z]?|-)\s+(?P<entry>\S.*?)\s{2,}A\d+\s+(?P<exit_no>\d+(?:\.\d+)?[a-z]?|-)\s+(?P<exit>\S.*?)\s{2,}" + PRICES),
}
GARE_ROW = re.compile(r"^\s*\d{5}\s+(?P<exit>\S.*?)\s{2,}" + r"\s+".join(f"(?P<c{i}>[\\d ]+,\\d\\d)" for i in range(1, 6)) + r"\s*$")
MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def valid_from(text):
    m = re.search(r"(?:(?:en vigueur|applicables?|TTC|Tarifs) (?:au|à compter du)|^à compter du) (\d+)(?:er)? (\w+) (\d{4})", text, re.I | re.M)
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" if m else ""


def key(name):
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()


def grid_rows(d, fetched, manifest):
    """Yields (url, sha256, url4, sha256_4, valid_from, entry, exit, class3, class4,
    entry exit number, exit exit number) for a grid document. A station
    spelled two ways in the document ("Pamiers Nord", "Pamiers nord") gets
    its most frequent spelling."""
    import pymupdf
    import grid
    prices, src, spell, vf, numbers = {3: {}, 4: {}}, {}, Counter(), "", {}
    for f in d.get("files", [d.get("file")]):
        doc = pymupdf.open(os.path.join(fetched, f))
        for page in doc:
            text = page.get_text()
            m = re.search(r"CLASSE\s+(\d)", text)
            if not m or int(m.group(1)) not in prices:
                continue
            vf = vf or valid_from(text)
            src[int(m.group(1))] = manifest[f]
            for a, b, p in grid.page_pairs(page, numbers):
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
    nums = {}
    for n, v in numbers.items():
        nums.setdefault(best.get(key(n), n), v)
    for (a, b), (p3, p4) in out.items():
        yield s3["url"], s3["sha256"], "" if same else s4["url"], "" if same else s4["sha256"], vf, a, b, p3, p4, nums.get(a, ""), nums.get(b, "")
    print(f"{d['operator']}: {len(prices[3])} class 3 and {len(prices[4])} class 4 grid cells, {len(out)} pairs, valid from {vf}")


def main(docs_path, fetched, out):
    docs = json.load(open(docs_path, encoding="utf-8"))["documents"]
    manifest = {f["file"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    with open(out, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["operator", "document", "url", "sha256", "url4", "sha256_4", "valid_from", "entry", "exit", "km", "class3", "class4", "entry_no", "exit_no"])
        for d in docs:
            if d["parser"] == "items":
                # Saved in the repository (documents.json's folder): text
                # positions written in a browser (sanef/extract.js).
                import sanef
                meta, prices, numbers, vf, report = sanef.parse(os.path.join(os.path.dirname(os.path.abspath(docs_path)), d["file"]))
                sha = meta["sha256"].replace(" ", "")
                for (a, b), p3 in prices.get(3, {}).items():
                    p4 = prices.get(4, {}).get((a, b))
                    if p4 is not None:
                        w.writerow([d["operator"], d["file"], meta["url"], sha, "", "", vf, a, b, "", p3, p4, numbers.get(a, ""), numbers.get(b, "")])
                print(f"{d['file']}: {len(prices.get(3, {}))} class 3 and {len(prices.get(4, {}))} class 4 prices, valid from {vf}, {report}")
                continue
            if d["parser"] == "columns":
                # A page's small tables (ATMB): after each "after" marker, the
                # column headings ("labels", checked to be there in order),
                # then the class 3 and class 4 rows of prices in EUR including
                # VAT; each column is a pair, a barrier priced alone, or null
                # (an exit's own booth beside the road: left out).
                text = re.sub(r"\s+", " ", open(os.path.join(fetched, d["file"]), encoding="utf-8").read())
                src = manifest[d["url_from"]]
                vf, n = valid_from(text), 0
                for tb in d["tables"]:
                    seg = text[text.index(tb["after"]):]
                    at = 0
                    for label in tb["labels"]:
                        at = seg.index(label, at)
                    rows = {c: [num(p) for p in re.findall(r"([\d ]*\d,\d\d) €", re.search(r"Classe " + c + r" [^€]*?((?:[\d ]*\d,\d\d € ?)+)", seg[at:]).group(1))]
                            for c in ("3", "4")}
                    assert len(rows["3"]) == len(rows["4"]) == len(tb["columns"]), (tb["after"], rows)
                    for i, col in enumerate(tb["columns"]):
                        if col:
                            a, b = (col, col) if isinstance(col, str) else col
                            w.writerow([d["operator"], d["url_from"], src["url"], src["sha256"], "", "", vf, a, b, "", rows["3"][i], rows["4"][i], "", ""])
                            n += 1
                print(f"{d['file']}: {n} pairs, valid from {vf}")
                continue
            if d["parser"] in ("gares", "barrier"):
                text = open(os.path.join(fetched, d["file"]), encoding="utf-8").read()
                src = manifest[d["url_from"]]
                # The date: the document's own, else the page linking it ("dated_by").
                vf = valid_from(text) or (valid_from(open(os.path.join(fetched, d["dated_by"]), encoding="utf-8").read()) if d.get("dated_by") else "")
                n = 0
                if d["parser"] == "gares":
                    # One page per entry station ("Gare de BAZAS"), then
                    # "code EXIT c1 c2 c3 c4 c5" rows (EUR including VAT).
                    entry = None
                    for line in text.splitlines():
                        g = re.search(r"Gare de ([A-ZÀ-Ü' -]*[A-ZÀ-Ü])", line)
                        if g:
                            entry = g.group(1).strip()
                        m = GARE_ROW.match(line)
                        if m and entry:
                            w.writerow([d["operator"], d["url_from"], src["url"], src["sha256"], "", "", vf, entry, m["exit"].strip(), "",
                                        num(m["c3"]), num(m["c4"]), "", ""])
                            n += 1
                else:
                    # A single barrier: its first five price rows are classes
                    # 1 to 5 (two seasons' prices; trucks pay the same in both).
                    rows = [re.findall(r"([\d ]+,\d\d) €", line) for line in text.splitlines()]
                    rows = [r for r in rows if len(r) == 2][:5]
                    st = d["station"]
                    w.writerow([d["operator"], d["url_from"], src["url"], src["sha256"], "", "", vf, st, st, "",
                                num(rows[2][1]), num(rows[3][1]), "", ""])
                    n = 1
                print(f"{d['file']}: {n} pairs, valid from {vf}")
                continue
            if d["parser"] == "grid":
                for url, sha, url4, sha4, vf, a, b, p3, p4, na, nb in grid_rows(d, fetched, manifest):
                    w.writerow([d["operator"], d.get("files", [d.get("file")])[0], url, sha, url4, sha4, vf, a, b, "", p3, p4, na, nb])
                continue
            text = open(os.path.join(fetched, d["file"]), encoding="utf-8").read()
            src = manifest[d["url_from"]]
            vf, n = valid_from(text), 0
            for line in text.splitlines():
                m = PARSERS[d["parser"]].match(line)
                if m:
                    g = m.groupdict()
                    km = num(g["km"]) if "km" in g else ""
                    w.writerow([d["operator"], d["url_from"], src["url"], src["sha256"], "", "", vf, m["entry"].strip(), m["exit"].strip(),
                                km, num(m["c3"]), num(m["c4"]), g.get("entry_no", "").strip("-"), g.get("exit_no", "").strip("-")])
                    n += 1
            lines = text.count(" €") // 5
            print(f"{d['file']}: {n} pairs (about {lines} price rows in the text), valid from {vf}")


if __name__ == "__main__":
    main(*sys.argv[1:])
