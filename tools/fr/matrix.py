"""Reads SFTRF's A43 price tables (Tarifs_autoroute_2026_2.pdf): one page
with four square tables, one per class ("Classe3" and "Classe4" are the
trucks'), each starting at its title. Rows are the stations, from
"30 Modane (vers l'Italie)" down, each with one price per column ("‐":
none), the name a point or two from its prices; the columns are the same stations, in the same order, without
Modane. The table is symmetric, which the reader checks.

Usage: python3 matrix.py file.pdf -> "class|entry|exit|price" lines
"""
import re, sys
from collections import defaultdict
import pymupdf

PRICE = re.compile(r"^\d+,\d\d$|^‐$|^-$")


def tables(path):
    page = pymupdf.open(path)[0]
    words = page.get_text("words")
    titles = [(w[0], w[1], int(w[4][6:])) for w in words if re.fullmatch(r"Classe\d", w[4])]
    out = {}
    for x, y, cls in titles:
        below = [t for t in titles if abs(t[0] - x) < 50 and t[1] > y]
        y1 = min([t[1] for t in below], default=page.rect.height)
        right = [t for t in titles if t[0] > x + 50 and abs(t[1] - y) < 50]
        x1 = min([t[0] for t in right], default=page.rect.width)
        ws = [w for w in words if x - 10 <= w[0] < x1 - 10 and y < w[1] < y1]
        lines, last = defaultdict(list), None
        for w in sorted(ws, key=lambda w: w[1]):
            if last is None or w[1] - last > 1.2:
                key = w[1]
            last = w[1]
            lines[key].append(w)
        names, values = [], []
        for y, r in sorted(lines.items()):
            r = sorted(r, key=lambda w: w[0])
            # A row's label: its exit number ("-" for a barrier), then its name.
            labelled = len(r) > 1 and re.fullmatch(r"\d{1,2}|-", r[0][4]) and re.search(r"[A-Za-z]", r[1][4])
            cells = [w for w in (r[1:] if labelled else r) if PRICE.match(w[4])]
            if labelled:
                names.append((y, " ".join(w[4] for w in r[1:] if not PRICE.match(w[4]))))
            if len(cells) >= 10:
                values.append((y, [None if c[4] in "‐-" else float(c[4].replace(",", ".")) for c in cells]))
        # A row's name sits a point or two from its prices.
        table = []
        for y, cells in values:
            ny, name = min(names, key=lambda n: abs(n[0] - y))
            assert abs(ny - y) < 4, (y, ny, name)
            table.append((name, cells))
        out[cls] = table
    return out


def pairs(table):
    names = [n for n, _ in table]
    cols = names[1:]  # the columns: every row's station but the first (Modane)
    got = {}
    for name, cells in table:
        assert len(cells) == len(cols), (name, len(cells), len(cols))
        for c, p in zip(cols, cells):
            if p is not None and c != name:
                got[(name, c)] = p
    for (a, b), p in got.items():
        if (b, a) in got:
            assert got[(b, a)] == p, (a, b, p, got[(b, a)])
    return {tuple(sorted(k)): p for k, p in got.items()}


if __name__ == "__main__":
    for cls, t in sorted(tables(sys.argv[1]).items()):
        for (a, b), p in pairs(t).items():
            print(f"{cls}|{a}|{b}|{p}")
