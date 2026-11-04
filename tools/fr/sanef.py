"""Reads Sanef's and SAPN's tariff brochures from their text positions
(tools/fr/sanef/*.items.txt, written by tools/fr/sanef/extract.js in a
browser: the site refuses scripted downloads).

Usage: python3 sanef.py file.items.txt -> "class|entry|exit|price" lines

Each page prices one class ("CLASSE" and a large digit). Its grids are
triangles: every row ends with a station's name and exit number
("BOULOGNE SUD N°28"), after its prices to the stations above it, one
per column. A station's column is the one its name starts in, just
right of its row's last price (a station on a branch may share none of
its neighbours' columns; one with no prices of its own still has its
column). A name in the first column starts a new triangle. A name may continue on the next line ("(péage d'Haudricourt)").
A barrier across an open section is priced on its own line, name then
price ("PEAGE DE CHAMBOURCY 12,40"): it becomes the pair (barrier,
barrier). Other rows where prices come after the name (an exit's own
booth, under the triangles) are left out and counted.
"""
import re, sys
from collections import defaultdict

PRICE = re.compile(r"^\d+,\d\d?$")


def items(path):
    meta, out = {}, []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("# ") and " " in line[2:]:
            k, v = line[2:].split(" ", 1)
            meta.setdefault(k, v)
            continue
        if not line or line.startswith("#"):
            continue
        p, x, y, w, h, f, t = line.split("|", 6)
        out.append((int(p), float(x), float(y), float(w), float(f), t.strip()))
    return meta, out


def clean(name):
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\s*/?\s*\(?A\d+[a-z]?\)?\s*$", "", name)  # road: "(A28)", "/ A150", "A151", "(A13a)"
    return re.sub(r"\s*/\s*$", "", name).strip()


def page_pairs(its, report):
    cls = None
    for i, (p, x, y, w, f, t) in enumerate(its):
        if t == "CLASSE" and i + 1 < len(its) and re.fullmatch(r"\d", its[i + 1][5]):
            cls = int(its[i + 1][5])
    if cls is None:
        return None, []
    # The grid's text: not the page title, nor the section headings
    # ("AUTOROUTES A16 - A29") beside the triangles.
    body = [v for v in its if v[4] < 8 and not v[5].startswith("AUTOROUTES")]
    rows = defaultdict(list)
    ys = []
    for v in sorted(body, key=lambda v: -v[2]):
        if not ys or ys[-1] - v[2] > 1.0:
            ys.append(v[2])
        rows[ys[-1]].append(v)
    cells = [v for v in body if PRICE.match(v[5])]
    centres = sorted(round(v[1] + v[3] / 2, 1) for v in cells)
    gaps = sorted(b - a for a, b in zip(centres, centres[1:]) if b - a > 2)
    step = gaps[len(gaps) // 10] if gaps else 13.8  # the column spacing
    c0 = centres[0] if centres else 0
    lines = []
    for key in sorted(rows, reverse=True):
        r = sorted(rows[key], key=lambda v: v[1])
        name_at = next((v[1] for v in r if not PRICE.match(v[5])), None)
        if name_at is None:
            continue
        pre = [v for v in r if PRICE.match(v[5]) and v[1] < name_at]
        post = [v for v in r if PRICE.match(v[5]) and v[1] > name_at]
        words, end = [], None
        for v in r:
            if PRICE.match(v[5]) or v[1] < name_at:
                continue
            if end is not None and v[1] - end > 20:
                break  # a road label further right
            words.append(v[5])
            end = v[1] + v[3]
        if post:
            # A barrier across an open section, priced on its own
            # ("PEAGE DE CHAMBOURCY 12,40"; Montesson's first line is its
            # base price, the next its off-peak one). Other such rows (an
            # exit's own booth under a triangle) are left out.
            if r[0][5].startswith("PEAGE DE ") and r[0][1] < post[0][1]:
                name = clean(r[0][5])
                report.setdefault("barriers", {}).setdefault(name, float(post[0][5].replace(",", ".")))
            else:
                report["after"] += 1
            continue
        text = " ".join(words)
        no = re.search(r"N°\s*([\d.]+)", text)
        name = clean(re.sub(r"N°\s*[\d.]+", "", text))
        cols = {round((v[1] + v[3] / 2 - c0) / step): float(v[5].replace(",", ".")) for v in pre}
        lines.append({"name": name, "no": no.group(1) if no else "", "x": name_at, "cols": cols})
    # A line starting "(" with no prices continues the name above it.
    merged = []
    for ln in lines:
        if merged and not ln["cols"] and ln["name"].startswith("(") and abs(ln["x"] - merged[-1]["x"]) < 1:
            merged[-1]["name"] = clean(merged[-1]["name"] + " " + ln["name"])
            continue
        merged.append(ln)
    # A station's own column is the one its name starts in (just right
    # of its row's last price); not every station has one.
    pairs, tri = [], {}
    for ln in merged:
        col = int((ln["x"] - (c0 - step / 2)) // step)
        if col == 0:
            tri = {}  # a name in the first column starts a new triangle
        for k, p in ln["cols"].items():
            if k in tri:
                pairs.append((tri[k], ln["name"], p))
            else:
                report["unplaced"] += 1
        tri[col] = ln["name"]
    for ln in merged:
        if ln["no"]:
            report.setdefault("numbers", {})[ln["name"]] = ln["no"]
    return cls, pairs


def valid_from(its):
    for v in its:
        m = re.search(r"TARIFS DE PEAGE TTC AU (\d\d)/(\d\d)/(\d{4})", v[5])
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def parse(path):
    """(header, {class: {(a, b): price}}, {station: exit number}, valid
    from, report) for an items file."""
    meta, its = items(path)
    by_page = defaultdict(list)
    for v in its:
        by_page[v[0]].append(v)
    report = defaultdict(int)
    out = {}
    for p in sorted(by_page):
        cls, pairs = page_pairs(by_page[p], report)
        if cls is None:
            continue
        for a, b, price in pairs:
            out.setdefault(cls, {})[(a, b)] = price
        for name, price in report.pop("barriers", {}).items():
            out.setdefault(cls, {})[(name, name)] = price
    numbers = report.pop("numbers", {})
    return meta, out, numbers, valid_from(its), dict(report)


if __name__ == "__main__":
    meta, out, numbers, vf, report = parse(sys.argv[1])
    for c in sorted(out):
        for (a, b), p in out[c].items():
            print(f"{c}|{a}|{b}|{p}")
    print({c: len(v) for c, v in out.items()}, report, "valid from", vf, file=sys.stderr)
