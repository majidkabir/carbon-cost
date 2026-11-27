"""Reads Bulgaria's tolled roads from the law into tools/roads/bg-network.json.

Usage: python3 bg_network.py list.html [segments.txt] > bg-network.json

list.html: Държавен вестник бр. 34/2025, Решение № 238 на Министерския
съвет от 22 април 2025 г.: the list of the republican roads on which the
toll is charged (тол такса), by number: the motorways (Автомагистрали),
the class I roads (Пътища първи клас) and the class II roads (Пътища
втори клас) it names; not the other class II roads. Its note: no toll on
the stretches inside settlements marked by the D11 and D12 signs, nor on
bypasses and ring roads inside them (build.py leaves out the national
roads' stretches in built-up land).

segments.txt: pdftotext -layout of the list it repealed, Решение № 680 от
2022 г. (ДВ бр. 78/2022), which gave each road's toll segments with their
lengths, in both directions; the decree of 2025 says the tolled network
stays the same. Its km by road (half the sum of both directions) are kept
to check the build's against.
"""
import html, json, re, sys
from html.parser import HTMLParser

SECTIONS = (("mw", "Автомагистрали"), ("I", "Пътища първи клас"), ("II", "Пътища втори клас"))


class Rows(HTMLParser):
    """The text of each table row, and of the text outside tables, in
    order."""

    def __init__(self):
        super().__init__()
        self.items, self.row, self.cell, self.depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.items.append(("row", self.row))
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif self.row is None and data.strip():
            self.items.append(("text", re.sub(r"\s+", " ", data).strip()))


def roads(page):
    p = Rows()
    p.feed(page)
    out, sec = {"mw": [], "I": [], "II": []}, None
    for kind, v in p.items:
        text = v if kind == "text" else " ".join(v)
        for key, head in SECTIONS:
            if head in text and (kind == "text" or len(v) <= 2):
                sec = key
        # A table's rows of column numbers ("1 2 3") aren't roads.
        if kind != "row" or sec is None or not v or all(c.isdigit() for c in v):
            continue
        num = v[0].replace("А", "A")  # Cyrillic А-1
        m = re.match(r"(A)\W?(\d)\b" if sec == "mw" else r"(\d{1,2})\b", num)
        if m:
            road = f"A-{m.group(2)}" if sec == "mw" else m.group(1)
            if road not in out[sec]:
                out[sec].append(road)
        else:
            print("bg_network: row not read:", sec, v[:2], file=sys.stderr)
    return out


def segment_km(text):
    """Km by road number (A-1, 1, 11), half the sum of the segments of
    both directions."""
    km = {}
    for l in text.splitlines():
        m = re.match(r"^\s*(Автомагистрала|Първи клас|Втори клас)\s+(\S+)\s.*?\b\d{10}\b.*?\s(\d+)\s+(\d+\.\d{3})\s*$", l)
        if m:
            road = m.group(2).replace("А", "A")
            km[road] = km.get(road, 0) + float(m.group(4)) / 2
    return {k: round(v, 1) for k, v in km.items()}


if __name__ == "__main__":
    page = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    doc = {
        "source": "Решение № 238 на Министерския съвет от 22 април 2025 г., ДВ бр. 34/2025: https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=234264",
        "roads": roads(page),
    }
    if len(sys.argv) > 2:
        doc["segments_2022"] = {
            "source": "Решение № 680 от 2022 г., ДВ бр. 78/2022: https://dv.parliament.bg/DVPics/2022/78_22/6119.pdf",
            "km": segment_km(open(sys.argv[2], encoding="utf-8").read()),
        }
    json.dump(doc, sys.stdout, ensure_ascii=False, indent=1)
    print()
