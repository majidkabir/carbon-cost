"""Reads VINCI Autoroutes' class grids (ASF's "maille" PDFs, the class
pages of the Escota guide): each page prices one vehicle class, in one
or more grids of cells, with station names written diagonally above the
columns (in the triangular grids, along the diagonal, where each name
also ends its row) or beside the rows, left or right.

Usage: python3 grid.py grid.pdf [page] -> "page|row station|column station|price"
lines on stdout; cells it couldn't name on stderr (DEBUG=2 also lists
the names and where it put them).

Cells are the horizontal words that are prices, or "." or "---" for no
price; a page's cells form separate grids where they stop being next to
each other. A grid's columns and rows are where its cells line up. A
column's station is the diagonal name starting at it (a name a fixed
distance from its column; a second line, and the circled exit number
before it, belong to it); a row's is the run of words next to its first
or last cell, else the diagonal name at its height.
"""
import os, re, sys
from collections import defaultdict
import pymupdf

DEBUG = False
DIGITS = set("0123456789,")
BADGE = re.compile(r"\d+(\.\d+)?[a-z]?")  # circled exit number: 11, 11.1, 40a
CELL = re.compile(r"^(\d+(,\d+)?|\.|-{2,3})$")  # a price, or no price (".", "---")


def cluster(vals, tol):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def nearest(cs, v, tol):
    best = min(range(len(cs)), key=lambda i: abs(cs[i] - v)) if cs else None
    return best if best is not None and abs(cs[best] - v) <= tol else None


def clean(t):
    t = re.sub(r"-\s+", "-", re.sub(r"\s+", " ", t)).strip()
    t = re.sub(r"^\.?\d+(\.\d+)?[a-z]?\s+", "", t)  # exit number
    return re.sub(r"\s*\((accès|système|sortie|entrée|péage en)[^)]*\)?\s*$", "", t, flags=re.I).strip()


def hwords(page):
    """Words of the horizontal text lines only (prices, row names), as
    (x0, y0, x1, y1, word); diagonal names and their exit numbers left out."""
    out = []
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            if abs(l["dir"][1]) > 0.05:
                continue
            for s in l["spans"]:
                cur = []
                for ch in s["chars"] + [None]:
                    # Dense rows run prices together with no space, only a
                    # small gap: "125,6125,6".
                    if ch is not None and cur and ch["c"] in DIGITS and cur[-1]["c"] in DIGITS \
                            and ch["bbox"][0] - cur[-1]["bbox"][2] > 0.3:
                        out.append((min(c["bbox"][0] for c in cur), min(c["bbox"][1] for c in cur),
                                    max(c["bbox"][2] for c in cur), max(c["bbox"][3] for c in cur),
                                    "".join(c["c"] for c in cur)))
                        cur = []
                    if ch is None or ch["c"].isspace():
                        if cur:
                            out.append((min(c["bbox"][0] for c in cur), min(c["bbox"][1] for c in cur),
                                        max(c["bbox"][2] for c in cur), max(c["bbox"][3] for c in cur),
                                        "".join(c["c"] for c in cur)))
                        cur = []
                    else:
                        cur.append(ch)
    return out


def page_pairs(page, numbers=None):
    """The page's (row station, column station, price) cells. If numbers
    is a dict, it also gets each station's exit number, where one is shown."""
    d = page.get_text("dict")
    cells, diag = [], []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            # Diagonal names and exit numbers.
            if t and l["dir"][0] > 0.3 and l["dir"][1] < -0.3:
                ox, oy = l["spans"][0]["origin"]
                diag.append((ox, oy, t, l["spans"][0]["size"]))

    words = hwords(page)
    alpha = [(x0, (y0 + y1) / 2) for x0, y0, x1, y1, w, *_ in words if re.search(r"[A-Za-zÀ-ÿ]", w)]
    for x0, y0, x1, y1, w, *_ in words:
        y = (y0 + y1) / 2
        # A number just before a name is its circled exit number.
        badge = any(0 <= ax - x1 <= 8 and abs(ay - y) <= 2.5 for ax, ay in alpha)
        if CELL.match(w) and not badge and (w == "." or (x1 - x0) >= (y1 - y0) * 0.3) and (y1 - y0) < 9:
            cells.append(((x0 + x1) / 2, y, w))
    if not cells:
        return []
    # A page may hold several grids, under or beside one another: cells
    # one or two steps apart belong to the same grid.
    xs = sorted(cells)
    dx = sorted(b[0] - a[0] for a, b in zip(xs, xs[1:]) if abs(b[1] - a[1]) < 2 and b[0] - a[0] > 3)
    ys = cluster([c[1] for c in cells], 2.0)
    dy = sorted(b - a for a, b in zip(ys, ys[1:]))
    cw = dx[len(dx) // 4] if dx else 10
    rh = dy[len(dy) // 4] if dy else 10
    parent = list(range(len(cells)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    buckets = defaultdict(list)
    for i, (x, y, _) in enumerate(cells):
        buckets[(int(x // (2 * cw)), int(y // (2 * rh)))].append(i)
    for i, (x, y, _) in enumerate(cells):
        bx, by = int(x // (2 * cw)), int(y // (2 * rh))
        for kx in (bx - 1, bx, bx + 1):
            for ky in (by - 1, by, by + 1):
                for j in buckets.get((kx, ky), ()):
                    if j < i and abs(cells[j][0] - x) < 2.2 * cw and abs(cells[j][1] - y) < 2.2 * rh:
                        parent[find(i)] = find(j)
    comp = [find(i) for i in range(len(cells))]

    def owner(x, y):
        # The grid of the cell nearest to a name.
        return comp[min(range(len(cells)), key=lambda i: (cells[i][0] - x) ** 2 + (cells[i][1] - y) ** 2)]
    dg, wg = defaultdict(list), defaultdict(list)
    for v in diag:
        dg[owner(v[0], v[1])].append(v)
    for w in words:
        wg[owner(w[0], (w[1] + w[3]) / 2)].append(w)
    out = []
    for k in sorted(set(comp)):
        cs = [c for c, g in zip(cells, comp) if g == k]
        if len(cs) >= 2:
            out += grid_pairs(cs, dg[k], wg[k], numbers)
    return out


def grid_pairs(cells, diag, words, numbers=None):
    if not cells:
        return []
    # The names in the corner boxes, larger than the stations', are
    # directions (Lyon, Toulouse Espagne).
    sizes = sorted(v[3] for v in diag if not BADGE.fullmatch(v[2]))
    if sizes:
        diag = [v for v in diag if v[3] <= sizes[len(sizes) // 2] * 1.15]
    # Grid columns hold many cells; circled exit numbers next to the row
    # names don't line up.
    cols = cluster([c[0] for c in cells], 3)
    cols = [c for c in cols if sum(abs(x - c) <= 3 for x, _, _ in cells) >= 3]
    allcells, cells = cells, [c for c in cells if nearest(cols, c[0], 3) is not None]
    rows = cluster([c[1] for c in cells], 2.0)
    cw = min(b - a for a, b in zip(cols, cols[1:])) if len(cols) > 1 else 10
    rh = min(b - a for a, b in zip(rows, rows[1:])) if len(rows) > 1 else 10
    colname, rowname = {}, {}
    # A station's name may run over a second line, which starts just
    # under the first (along the text the same place, across it one line
    # lower), and may follow a circled exit number a few points before it
    # along the text. Neighbouring stations' names start a column apart.
    def along(ax, ay, bx, by):
        return ((bx - ax) - (by - ay)) * 0.7071

    def across(ax, ay, bx, by):
        return ((bx - ax) + (by - ay)) * 0.7071
    badges = [(ox, oy, t) for ox, oy, t, _ in diag if BADGE.fullmatch(t)]

    def badge_of(x, y, tol=2):
        b = [p for p in badges if 2 < along(p[0], p[1], x, y) < 12 and abs(across(p[0], p[1], x, y)) < tol]
        return min(b, key=lambda p: abs(across(p[0], p[1], x, y))) if b else None
    names = []
    for ox, oy, t, size in sorted((v for v in diag if not BADGE.fullmatch(v[2])), key=lambda v: v[0] + v[1]):
        prev = [g for g in names if abs(along(*g[-1][:2], ox, oy)) < 3 and 0 < across(*g[-1][:2], ox, oy) < 1.25 * g[-1][3]]
        if prev and badge_of(ox, oy) is None:
            prev[-1].append((ox, oy, t, size))
        else:
            names.append([(ox, oy, t, size)])
    groups = []
    for g in names:
        # A two-line name's number may sit level with the middle of the two.
        b = badge_of(*g[0][:2], tol=2 if len(g) == 1 else 4.5)
        groups.append(([b] if b else []) + g)
    named = []
    for g in groups:
        name = clean(" ".join(v[2] for v in g if len(v) == 4))
        if re.search(r"[A-Za-zÀ-ÿ]{2}", name):
            named.append((g[0][0], g[0][1], name))
            if numbers is not None and len(g[0]) == 3:
                numbers.setdefault(name, g[0][2])
    # A name starts a fixed distance from its column's centre. The last
    # stations' columns hold too few cells to be found from the cells
    # alone (and the very last has none): place them from their names.
    offs = sorted(cols[c] - ox for ox, _, _ in named if (c := nearest(cols, ox, cw * 0.6)) is not None)
    if offs:
        off = offs[len(offs) // 2]
        extra = [ox + off for ox, _, _ in named if nearest(cols, ox + off, cw * 0.6) is None]
        cols = sorted(cols + extra)
        cells = [c for c in allcells if nearest(cols, c[0], 3) is not None and nearest(rows, c[1], rh / 2) is not None]
    top = {}
    for ox, oy, name in named:
        c = nearest(cols, ox + (off if offs else 0), cw * 0.6)
        if c is not None and c not in colname:
            colname[c], top[c] = name, oy
        # In the triangular part the name also ends its row.
        r = nearest(rows, oy, rh * 0.6)
        if DEBUG > 1:
            print("name", round(ox), round(oy), name, "col", c is not None and round(cols[c]), "row", r is not None and round(rows[r]), file=sys.stderr)
        if r is not None:
            rowname.setdefault(r, name)
    # Row names written beside the rows: to their left, or on some pages
    # to their right.
    first_x, last_x = defaultdict(lambda: 1e9), defaultdict(lambda: -1e9)
    for x, y, t in cells:
        r = nearest(rows, y, rh / 2)
        first_x[r] = min(first_x[r], x)
        last_x[r] = max(last_x[r], x)
    # A row's name is the run of words next to its first (or last) cell,
    # each a short gap from the next: a map or another grid further off
    # isn't part of it.
    inrow = defaultdict(list)
    for x0, y0, x1, y1, w, *_ in words:
        r = nearest(rows, (y0 + y1) / 2, rh / 2)
        if r is not None and (y1 - y0) < 12:
            inrow[r].append((x0, x1, w))
    for r, ws in inrow.items():
        ws.sort()
        left, edge = [], first_x[r] - cw / 2
        for x0, x1, w in reversed([v for v in ws if v[1] <= first_x[r] + 1]):
            if edge - x1 > 20:
                break
            left.insert(0, w)
            edge = x0
        right, edge = [], last_x[r] + cw / 2
        for x0, x1, w in [v for v in ws if v[0] >= last_x[r] + 1]:
            if x0 - edge > 20:
                break
            right.append(w)
            edge = x1
        for side in (left, right):
            name = clean(" ".join(w for w in side if not re.match(r"^A\d+[A-Z]?$", w)))
            if re.search(r"[A-Za-zÀ-ÿ]{2}", name):
                rowname[r] = name
                n = [w for w in side if BADGE.fullmatch(w)]
                if numbers is not None and n:
                    numbers.setdefault(name, n[0])
                break
    out, miss = [], defaultdict(int)
    for x, y, t in cells:
        if not t[0].isdigit():
            continue
        r, c = nearest(rows, y, rh / 2), nearest(cols, x, cw / 2)
        if c in top and y < top[c]:
            continue  # above its column's name: not part of the grid
        if r in rowname and c in colname and rowname[r] != colname[c]:
            out.append((rowname[r], colname[c], float(t.replace(",", "."))))
        elif r not in rowname or c not in colname:
            miss[("row" if r not in rowname else "") + ("col" if c not in colname else "")] += 1
    if DEBUG and miss:
        print("unnamed cells:", dict(miss), "rows", [round(rows[r]) for r in range(len(rows)) if r not in rowname],
              "cols", [round(cols[c]) for c in range(len(cols)) if c not in colname], file=sys.stderr)
    return out


if __name__ == "__main__":
    DEBUG = int(os.environ.get("DEBUG", 1))
    doc = pymupdf.open(sys.argv[1])
    pages = [int(sys.argv[2])] if len(sys.argv) > 2 else range(doc.page_count)
    for i in pages:
        for a, b, p in page_pairs(doc[i]):
            print(f"{i}|{a}|{b}|{p}")
