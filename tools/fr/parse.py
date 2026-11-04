"""Parses the tariff documents listed in documents.json (from fetch.py's
output folder) into pairs.csv: one row per document, entry and exit
station, with the tariff distance and the class 3 and class 4 prices in
EUR including VAT, and the date the document says they apply from.

Usage: python3 parse.py documents.json fetched/ pairs.csv

Parsers:
  list        ENTRY  EXIT  km  c1 €  c2 €  c3 €  c4 €  c5 €
  list_codes  code ENTRY  code EXIT  km  c1 €  c2 €  c3 €  c4 €  c5 € [km]
"""
import csv, json, os, re, sys

EUR = r"([\d ]+,\d\d) €"
PARSERS = {
    "list": re.compile(r"^\s*(?P<entry>\S.*?)\s{2,}(?P<exit>\S.*?)\s{2,}(?P<km>[\d ]+,\d+)\s+" + r"\s+".join([EUR] * 5)),
    "list_codes": re.compile(r"^\s*\d+\s+(?P<entry>\S.*?)\s{2,}\d+\s+(?P<exit>\S.*?)\s{2,}(?P<km>[\d ]+,\d+)\s+" + r"\s+".join([EUR] * 5)),
}
MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def valid_from(text):
    m = re.search(r"(?:en vigueur|applicables?) (?:au|à compter du) (\d+)(?:er)? (\w+) (\d{4})", text, re.I)
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" if m else ""


def main(docs_path, fetched, out):
    docs = json.load(open(docs_path, encoding="utf-8"))["documents"]
    manifest = {f["file"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    with open(out, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["operator", "document", "url", "sha256", "valid_from", "entry", "exit", "km", "class3", "class4"])
        for d in docs:
            text = open(os.path.join(fetched, d["file"]), encoding="utf-8").read()
            src = manifest[d["url_from"]]
            vf, n = valid_from(text), 0
            for line in text.splitlines():
                m = PARSERS[d["parser"]].match(line)
                if m:
                    w.writerow([d["operator"], d["url_from"], src["url"], src["sha256"], vf, m["entry"].strip(), m["exit"].strip(),
                                num(m["km"]), num(m.group(6)), num(m.group(7))])
                    n += 1
            lines = text.count(" €") // 5
            print(f"{d['file']}: {n} pairs (about {lines} price rows in the text), valid from {vf}")


if __name__ == "__main__":
    main(*sys.argv[1:])
