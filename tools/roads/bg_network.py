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
2022 г. (ДВ бр. 78/2022), which gave each road's toll segments, in both
directions, by their ends' coordinates and length; the government said
the list of 2025 doesn't change the tolled network, and the toll
operator's own list of segments (bgtoll.bg) refuses the workflow. The
segments leave out the settlements; build.py finds each segment of a
class I or II road between its ends along the road in OpenStreetMap.
"""
import json, math, re, sys
from html.parser import HTMLParser

SECTIONS = (("mw", "Автомагистрали"), ("I", "Пътища първи клас"), ("II", "Пътища втори клас"))


class Rows(HTMLParser):
    """The text of each table row, and the text outside rows, in order.
    The page lays the decree out in tables of tables: a row with rows in it
    is layout, its own text (a heading) text outside rows."""

    def __init__(self):
        super().__init__()
        self.data = []  # (row, cell, text)
        self.trs, self.tds, self.parent = [], [], {}
        self.n = 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.n += 1
            self.parent[self.n] = self.trs[-1] if self.trs else None
            self.trs.append(self.n)
        elif tag in ("td", "th"):
            self.n += 1
            self.tds.append(self.n)

    def handle_endtag(self, tag):
        if tag == "tr" and self.trs:
            self.trs.pop()
        elif tag in ("td", "th") and self.tds:
            self.tds.pop()

    def handle_data(self, data):
        if data.strip():
            self.data.append((self.trs[-1] if self.trs else None, self.tds[-1] if self.tds else None, data))

    @property
    def items(self):
        outer = {p for p in self.parent.values() if p is not None}
        out, rows = [], {}
        for tr, td, text in self.data:
            if tr is None or tr in outer:
                out.append(("text", re.sub(r"\s+", " ", text).strip()))
            elif tr not in rows:
                rows[tr] = {td: [text]}
                out.append(("row", rows[tr]))
            else:
                rows[tr].setdefault(td, []).append(text)
        return [(k, v if k == "text" else [re.sub(r"\s+", " ", "".join(c)).strip() for c in v.values()]) for k, v in out]


def roads(page):
    p = Rows()
    p.feed(page)
    out, sec = {"mw": [], "I": [], "II": []}, None
    for kind, v in p.items:
        text = v if kind == "text" else " ".join(v)
        for key, head in SECTIONS:
            if (kind == "text" and head in text) or (kind == "row" and any(c == head for c in v)):
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
        elif not re.match(r"Номер|[ЕE]\W?\d", num):  # the heads; the E roads' rows
            print("bg_network: row not read:", sec, v[:2], file=sys.stderr)
    return out


# A segment's row: its class, road, number and length in metres, on the
# line of its class; its start and end, the first two coordinates after
# the last segment's, in reading order (on the lines around it: the
# page's columns wrap).
ROW = re.compile(r"^\s*(Автомагистрал[аи]|Първи клас|Втори клас)\s+(\S+)\s.*?\b(\d{10})\b.*?\s(\d+)\s+(\d+\.\d{3})\s*$")
POINT = re.compile(r"(\d{2}\.\d+),\s*(\d{2}\.\d+);")
CLASS = {"Автомагистрала": "mw", "Автомагистрали": "mw", "Първи клас": "I", "Втори клас": "II"}


def segments(text):
    """The toll segments: [class, road, number, start lat, lon, end lat,
    lon, metres]."""
    lines = text.splitlines()
    points = [(float(m.group(1)), float(m.group(2))) for l in lines for m in [POINT.search(l)] if m]
    rows = [m for l in lines for m in [ROW.match(l)] if m]
    if len(points) != 2 * len(rows):
        raise SystemExit(f"bg_network: {len(rows)} segments but {len(points)} coordinates")
    out = []
    for k, m in enumerate(rows):
        (a, b), (c, d) = points[2 * k], points[2 * k + 1]
        metres = int(m.group(4))
        # The ends can't be further apart than the segment is long.
        if haversine(a, b, c, d) > metres * 1.02 + 60:
            raise SystemExit(f"bg_network: segment {m.group(3)} of {metres} m has ends {haversine(a, b, c, d):.0f} m apart")
        out.append([CLASS[m.group(1)], m.group(2).replace("А", "A"), m.group(3), a, b, c, d, metres])
    return out


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


if __name__ == "__main__":
    page = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    doc = {
        "source": "Решение № 238 на Министерския съвет от 22 април 2025 г., ДВ бр. 34/2025: https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=234264",
        "roads": roads(page),
    }
    if len(sys.argv) > 2:
        doc["segments_2022"] = {
            "source": "Решение № 680 от 2022 г., ДВ бр. 78/2022: https://dv.parliament.bg/DVPics/2022/78_22/6119.pdf",
            "rows": segments(open(sys.argv[2], encoding="utf-8").read()),
        }
    # One segment a line.
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    if "segments_2022" in doc:
        head, _, _ = text.partition('"rows": [')
        rows = ",\n".join("   " + json.dumps(r, ensure_ascii=False) for r in doc["segments_2022"]["rows"])
        text = head + '"rows": [\n' + rows + "\n  ]\n }\n}"
    print(text)
