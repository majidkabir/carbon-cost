"""Reads the section prices of a Slovenian toll price list annex (Cenik
cestnine za uporabo cestninskih cest, Priloga) from its PDF, as PISRS
serves it, with pdftotext -bbox word boxes.

Two layouts:
- 4 EURO groups (E 0-3, E4, E5, EEV/E6) for each of R2, R3, R4 side by
  side: 12 prices a row (the price lists until October 2025);
- 9 EURO/CO2 columns (EURO 0-III, IV, V, EEV, VI with CO2 classes 1-5),
  one table per toll class under its heading R2, R3 or R4 (from
  November 2025).

A row starts at its road's code (A1, H4, R2-437 ...) in the first
column; a section name or a price that doesn't fit its cell continues on
the next line (prices are split mid-number in some annexes), so each word
belongs to the row whose code is nearest above-or-level, or level within
half a line below. Returns [(road, name, {"R2": [...], "R3": [...],
"R4": [...]})] in the annex's order.

Usage: python3 si_annex.py annex.pdf (prints the rows)"""
import html, re, subprocess, sys

CODE = re.compile(r"^(A\d+|H\d+|[RG]\d-\d+)$")
NUM = re.compile(r"^\d+,\d+$")
DIGITS = re.compile(r"^\d+$")


def words(pdf):
    out = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, text=True, check=True).stdout
    pages = []
    for page in re.split(r"<page ", out)[1:]:
        ws = []
        for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', page):
            x0, y0, x1, y1 = map(float, m.groups()[:4])
            ws.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "yc": (y0 + y1) / 2, "t": html.unescape(m.group(5))})
        pages.append(ws)
    return pages


def rows(pdf):
    found, klass = [], None  # [code word, its words, class]
    for ws in words(pdf):
        if not ws:
            continue
        hs = sorted(w["y1"] - w["y0"] for w in ws if w["t"].strip())
        h = hs[len(hs) // 2]  # a line's height
        cands = [w for w in ws if CODE.match(w["t"])]
        if not cands:
            continue
        left = min(w["x0"] for w in cands)  # the road column (a name may hold a code too)
        codes = sorted((w for w in cands if w["x0"] < left + 10), key=lambda w: w["yc"])
        heads = sorted((w for w in ws if w["t"] in ("R2", "R3", "R4") and w["x0"] > 150), key=lambda w: w["yc"])
        if not codes:
            continue
        # The column where prices start.
        first_num = min(w["x0"] for w in ws if NUM.match(w["t"]))
        groups = [[] for _ in codes]
        # The table's head ends with the column titles' last line.
        head = [w for w in ws if w["yc"] < codes[0]["yc"] and re.match(r"^(ODSEK|CESTA|CO2.*|E\s?\d|EEV,?|EURO|VI|E6|0-III|IV|V)$", w["t"])]
        top = max((w["y1"] for w in head), default=codes[0]["y0"] - 3 * h)
        # A class's table head (from its R2/R3/R4 heading to its first row) isn't a name.
        bands = []
        for x in heads:
            below = [c["yc"] for c in codes if c["yc"] > x["yc"]]
            if below:
                bands.append((x["y0"], min(below) - 0.7 * h))
        for w in ws:
            if w in codes or w["yc"] < top or w["t"] in ("R2", "R3", "R4") or any(a <= w["yc"] <= b for a, b in bands):
                continue
            if w["yc"] < codes[0]["yc"] - 1.5 * h and found and not head:
                # The end of a name the previous page's last row began.
                w = dict(w, yc=w["yc"] + 10000)
                found[-1][1].append(w)
                continue
            # Nearest code line, the word's centre within a row's reach.
            i = min(range(len(codes)), key=lambda k: abs(w["yc"] - codes[k]["yc"]))
            if abs(w["yc"] - codes[i]["yc"]) > 2.5 * h:
                continue
            groups[i].append(w)
        for c, g in zip(codes, groups):
            # Klass: the last R2/R3/R4 heading above this row on the page (9-column layout).
            above = [x["t"] for x in heads if x["yc"] < c["yc"]]
            if above:
                klass = above[-1]
            found.append([c, g, klass, first_num, h])
    def name_lines(c, g, first_num, h):
        lines = []
        for w in sorted((w for w in g if w["x1"] < first_num - 2 and not DIGITS.match(w["t"])), key=lambda w: w["yc"]):
            if lines and abs(w["yc"] - lines[-1][0]["yc"]) < h / 2:
                lines[-1].append(w)
            else:
                lines.append([w])
        return [(sum(w["yc"] for w in ln) / len(ln), " ".join(w["t"] for w in sorted(ln, key=lambda w: w["x0"]))) for ln in lines]

    # A name that doesn't fit its cell wraps: some annexes start it on the
    # code's line (top-aligned), others centre it on that line. Each line
    # goes to the row it reads with: try both and keep the one whose names
    # don't start or end at a dash or leave a bracket open.
    all_lines = []
    for k, (c, g, klass, first_num, h) in enumerate(found):
        all_lines += [(k, y, t) for y, t in name_lines(c, g, first_num, h)]

    def names(top_aligned):
        got = [[] for _ in found]
        for k, y, t in all_lines:
            c, h = found[k][0], found[k][4]
            j = k
            if top_aligned and y < c["yc"] - h / 2 and k > 0:
                j = k - 1  # above its nearest code: the end of the row above
            got[j].append((y if j == k else y + 100000, t))
        return [" ".join(t for _, t in sorted(x)) for x in got]

    def bad(ns):
        return sum(1 for n in ns if re.search(r"(^[-–])|([-–]$)", n.strip()) or n.count("(") != n.count(")"))

    a, b = names(True), names(False)
    final = a if bad(a) <= bad(b) else b
    out = []
    for (c, g, klass, first_num, h), name in zip(found, final):
        nums = sorted((w for w in g if NUM.match(w["t"]) and w["x0"] >= first_num - 2), key=lambda w: w["x0"])
        for d in sorted((w for w in g if DIGITS.match(w["t"]) and w["x0"] >= first_num - 2), key=lambda w: w["yc"]):
            n = min(nums, key=lambda w: abs((w["x0"] + w["x1"]) / 2 - (d["x0"] + d["x1"]) / 2))
            if d["yc"] > n["yc"]:
                n["t"] += d["t"]
        prices = [float(w["t"].replace(",", ".")) for w in nums]
        if len(prices) == 12:
            out.append((c["t"], name, {"R2": prices[0:4], "R3": prices[4:8], "R4": prices[8:12]}))
        elif len(prices) == 9 and klass:
            out.append((c["t"], name, {klass: prices}))
        else:
            raise SystemExit(f"{pdf}: {c['t']} at y {c['yc']:.0f}: {name}: {len(prices)} prices {[w['t'] for w in nums]}")
    # The 9-column layout's three tables list the same sections in the same order.
    if out and len(out[0][2]) == 1:
        by = {k: [r for r in out if k in r[2]] for k in ("R2", "R3", "R4")}
        if not len(by["R2"]) == len(by["R3"]) == len(by["R4"]):
            raise SystemExit(f"{pdf}: rows per class {[len(v) for v in by.values()]}")
        out = []
        for a, b, c in zip(by["R2"], by["R3"], by["R4"]):
            if not a[0] == b[0] == c[0]:
                raise SystemExit(f"{pdf}: rows differ: {a[:2]} {b[:2]} {c[:2]}")
            # The R4 table's name column is the widest: its names wrap least.
            out.append((a[0], c[1], {**a[2], **b[2], **c[2]}))
    return out


def norm(name):
    """A section name compared without case, spacing around dashes, or dash kind."""
    s = name.upper().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s*\(\s*", " (", s)
    s = re.sub(r"\s*\)\s*", ") ", s)
    return re.sub(r"\s+", " ", s).strip()


if __name__ == "__main__":
    for r in rows(sys.argv[1]):
        print(r[0], "|", r[1], "|", r[2])
