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
  browser     tables read in a browser (browser/*.txt), triangles or
              barriers priced alone (Alicorne, ALiS, CCI Seine-Estuaire)
  matrix      square tables per class on one PDF page (SFTRF's A43, matrix.py)
  transcribed prices published only as images, transcribed by hand
              (transcribed/*.json), by EURO class (Atlandes, ALBEA)
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
import csv, hashlib, json, os, re, sys, unicodedata
from collections import Counter

PRICES = r"\s+".join(f"(?P<c{i}>[\\d ]+,\\d\\d) €" for i in range(1, 6))
PARSERS = {
    "list": re.compile(r"^\s*(?P<entry>\S.*?)\s{2,}(?P<exit>\S.*?)\s{2,}(?P<km>[\d ]+,\d+)\s+" + PRICES),
    "list_codes": re.compile(r"^\s*\d+\s+(?P<entry>\S.*?)\s{2,}\d+\s+(?P<exit>\S.*?)\s{2,}(?P<km>[\d ]+,\d+)\s+" + PRICES),
    "list_roads": re.compile(r"^\s*A\d+\s+(?P<entry_no>\d+(?:\.\d+)?[a-z]?|-)\s+(?P<entry>\S.*?)\s{2,}A\d+\s+(?P<exit_no>\d+(?:\.\d+)?[a-z]?|-)\s+(?P<exit>\S.*?)\s{2,}" + PRICES),
}
GARE_ROW = re.compile(r"^\s*\d{5}\s+(?P<exit>\S.*?)\s{2,}" + r"\s+".join(f"(?P<c{i}>[\\d ]+,\\d\\d)" for i in range(1, 6)) + r"\s*$")
AXLES = ("2 axles", "3 axles", "4+ axles")
MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def valid_from(text):
    m = re.search(r"(?:(?:en vigueur|applicables?|TTC|Tarifs) (?:au|à compter du)|^à compter du) (\d+)(?:er)? (\w+) (\d{4})", text, re.I | re.M)
    if m:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(?:TTC|applicables?) en euros au (\d\d)\.(\d\d)\.(\d{4})", text)  # "Prix TTC en euros au 01.02.2026"
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


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
        w.writerow(["operator", "document", "url", "sha256", "url4", "sha256_4", "valid_from", "entry", "exit", "km", "class3", "class4", "entry_no", "exit_no", "by_euro"])
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
            if d["parser"] == "browser":
                # Tables read in a browser from sites that refuse scripted
                # requests (browser/*.txt: the page's URL and date, then per
                # class either a triangle, one row per station ending with its
                # name after its prices to the stations above, "GRATUIT" being
                # 0, or a "barriers" line naming the columns of barriers priced
                # alone). The sha256 is the extract's.
                path = os.path.join(os.path.dirname(os.path.abspath(docs_path)), d["file"])
                raw = open(path, encoding="utf-8").read()
                head = dict(l[2:].split(" ", 1) for l in raw.splitlines() if l.startswith("# ") and " " in l[2:] and not l.startswith("# class"))
                barriers, cls, prices, order = None, None, {3: {}, 4: {}}, {}
                for line in raw.splitlines():
                    if line.startswith("# barriers|"):
                        barriers = line.split("|")[1:]
                    elif line.startswith("# class "):
                        cls, order[int(line[8:])] = int(line[8:]), []
                    elif line.startswith("#") or not line.strip():
                        continue
                    elif cls in prices:
                        cells = [c.replace("€", "").strip() for c in line.split("|")]
                        val = lambda c: 0.0 if c.upper() == "GRATUIT" else (num(c) if c else None)
                        if barriers:
                            for b, c in zip(barriers, cells):
                                prices[cls][(b, b)] = val(c)
                        else:
                            name, above = cells[-1], cells[:-1]
                            for k, c in enumerate(above):
                                if val(c) is not None:
                                    prices[cls][(order[cls][k], name)] = val(c)
                            order[cls].append(name)
                sha = hashlib.sha256(raw.encode()).hexdigest()
                for (a, b), p3 in prices[3].items():
                    if prices[4].get((a, b)) is not None:
                        w.writerow([d["operator"], d["file"], head["url"], sha, "", "", head.get("valid_from", "").strip(), a, b, "", p3, prices[4][(a, b)], "", ""])
                print(f"{d['file']}: {len(prices[3])} class 3 and {len(prices[4])} class 4 prices, valid from {head.get('valid_from', '')}")
                continue
            if d["parser"] == "matrix":
                # SFTRF's A43: square tables per class on one PDF page (matrix.py).
                import matrix
                src = manifest[d["file"]]
                t = matrix.tables(os.path.join(fetched, d["file"]))
                p3, p4 = matrix.pairs(t[3]), matrix.pairs(t[4])
                vf = valid_from(open(os.path.join(fetched, d["file"][:-4] + ".txt"), encoding="utf-8").read()) or d.get("valid_from", "")
                for (a, b), p in p3.items():
                    if (a, b) in p4:
                        w.writerow([d["operator"], d["file"], src["url"], src["sha256"], "", "", vf, a, b, "", p, p4[(a, b)], "", ""])
                print(f"{d['file']}: {len(p3)} class 3 and {len(p4)} class 4 pairs, valid from {vf}")
                continue
            if d["parser"] == "transcribed":
                # Prices an operator publishes only as an image, transcribed
                # by hand (transcribed/*.json: the image's URL and sha256,
                # which tools/tables checks). By EURO class: the by_euro
                # column holds them for the groups "<axles> EURO <n>"
                # (build.py), class3 and class4 the EURO 6 price.
                t = json.load(open(os.path.join(os.path.dirname(os.path.abspath(docs_path)), d["file"]), encoding="utf-8"))
                url, sha, vf, n = t["source"]["url"], t["source"]["sha256"], t["valid_from"], 0
                rows = []
                if "barriers" in t:
                    pr = t["prices"]
                    by = {f"{ax} EURO {e}": pr["2-3 axles" if ax in ("2 axles", "3 axles") else "4+ axles"][str(e)]
                          for ax in AXLES for e in range(7)}
                    rows = [(b, b, by) for b in t["barriers"]]
                else:
                    col = {e: t["columns"].index("0-3" if e <= 3 else str(e)) for e in range(7)}
                    for x, pr in t["exits"].items():
                        by = {f"{ax} EURO {e}": pr["3" if ax == "2 axles" else "4"][col[e]] for ax in AXLES for e in range(7)}
                        rows.append((t["entry"], x, by))
                for a, b, by in rows:
                    w.writerow([d["operator"], d["file"], url, sha, "", "", vf, a, b, "", by["2 axles EURO 6"], by["3 axles EURO 6"], "", "", json.dumps(by)])
                    n += 1
                print(f"{d['file']}: {n} pairs by EURO class, valid from {vf}")
                continue
            if d["parser"] == "columns":
                # A page's small tables (ATMB): after each "after" marker, the
                # column headings ("labels", checked to be there in order),
                # then the class 3 and class 4 rows of prices in EUR including
                # VAT; each column is a pair, a barrier priced alone, or null
                # (an exit's own booth beside the road: left out).
                text = re.sub(r"\s+", " ", open(os.path.join(fetched, d["file"]), encoding="utf-8").read())
                src = manifest[d["url_from"]]
                vf, n, out_rows, used = valid_from(text), 0, [], ""
                for tb in d["tables"]:
                    seg = text[text.index(tb["after"]):]
                    at = 0
                    for label in tb["labels"]:
                        at = seg.index(label, at)
                    used += seg[:seg.index("Classe 4", at) + 200]
                    rows = {c: [num(p) for p in re.findall(r"([\d ]*\d,\d\d) €", re.search(r"Classe " + c + r" [^€]*?((?:[\d ]*\d,\d\d € ?)+)", seg[at:]).group(1))]
                            for c in ("3", "4")}
                    assert len(rows["3"]) == len(rows["4"]) == len(tb["columns"]), (tb["after"], rows)
                    for i, col in enumerate(tb["columns"]):
                        if col:
                            a, b = (col, col) if isinstance(col, str) else col
                            out_rows.append([a, b, rows["3"][i], rows["4"][i]])
                            n += 1
                # The page also carries live traffic news: the sha256 is the
                # price tables' text's, so it changes only when they do.
                sha = hashlib.sha256(used.encode()).hexdigest()
                for a, b, p3, p4 in out_rows:
                    w.writerow([d["operator"], d["url_from"], src["url"], sha, "", "", vf, a, b, "", p3, p4, "", ""])
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
