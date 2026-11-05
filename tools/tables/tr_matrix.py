"""Reads a KGM motorway toll matrix from pdftotext -bbox output (word
boxes): stations down the left, a class column ("SINIF", 1 to 6), and a
price column per station across the top. Used by tr.py.

matrix(path) -> (row names, column names, {(row, column): {class: TL}}),
rows and columns by index in the order printed; a column's name is the
header words standing over its prices.
"""
import html, re, statistics

PRICE = re.compile(r"^\d+(\.\d{3})*,\d\d$")
DIST = re.compile(r"^\d+,\d{3}$")


def words(path):
    t = open(path, encoding="utf-8").read()
    pages = []
    for page in re.findall(r"<page .*?</page>", t, flags=re.S):
        pages.append([(float(a), float(b), float(c), float(d), html.unescape(w).replace("​", "").strip())
                      for a, b, c, d, w in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', page)])
    return pages


def key(name):
    """A station name compared without case, accents, spaces or punctuation."""
    s = name.replace("İ", "i").replace("I", "ı").lower()
    for a, b in zip("çğıöşüâî", "cgiosuai"):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def lines(ws, tol=1.5):
    out = []
    for w in sorted(ws, key=lambda w: (w[1] + w[3]) / 2):
        y = (w[1] + w[3]) / 2
        if out and abs(out[-1][0] - y) <= tol:
            out[-1][1].append(w)
        else:
            out.append([y, [w]])
    return [(y, sorted(l, key=lambda w: w[0])) for y, l in out]


def page_matrix(ws):
    ls = lines(ws)
    # Class lines: a lone digit 1-6 then prices only.
    cls = []
    for y, l in ls:
        for i, w in enumerate(l):
            if re.fullmatch(r"[1-6]", w[4]) and l[i + 1:] and all(PRICE.match(v[4]) for v in l[i + 1:]):
                cls.append((y, int(w[4]), w[0], l[i + 1:]))
                break
    if not cls:
        return [], [], {}
    cx = statistics.median(c[2] for c in cls)
    cls = [c for c in cls if abs(c[2] - cx) < 3]
    # Blocks of classes 1..6.
    blocks, cur = [], []
    for c in cls:
        if c[1] == 1:
            cur = [c]
            blocks.append(cur)
        elif cur and c[1] == cur[-1][1] + 1:
            cur.append(c)
    blocks = [b for b in blocks if [c[1] for c in b] == [1, 2, 3, 4, 5, 6]]
    if not blocks:
        return [], [], {}
    # Price columns: clusters of the values' right edges.
    vs = sorted((v[2], (v[0] + v[2]) / 2) for b in blocks for c in b for v in c[3])
    cols = []
    for x, m in vs:
        if cols and x - cols[-1][-1][0] < 8:
            cols[-1].append((x, m))
        else:
            cols.append([(x, m)])
    centers = [statistics.median(x for x, _ in c) for c in cols]
    mids = [statistics.median(m for _, m in c) for c in cols]
    width = min((b - a for a, b in zip(centers, centers[1:])), default=40)

    def col(x):
        i = min(range(len(centers)), key=lambda i: abs(centers[i] - x))
        return i if abs(centers[i] - x) < width / 2 else None
    # Header: words above the first block, right of the class column,
    # assigned to the column whose values they stand over.
    top = blocks[0][0][0]
    ist = min((w[1] for w in ws if key(w[4]) == "istasyon"), default=top - 40)
    first_dist = min((w[1] for w in ws if DIST.match(w[4])), default=top)
    head = [w for w in ws if ist - 12 < w[1] and w[3] < min(top, first_dist) - 1 and w[0] > cx + 4]
    heads = {}
    for y, l in lines(head):
        for w in l:
            if w[4] in ("ÇIKIŞ", "GİŞELERİ", "SINIF", "SINIFI", "ARAÇ") or re.fullmatch(r"[\d,.]+", w[4]):
                continue
            mid = (w[0] + w[2]) / 2
            # Header words are centred on their column; values are right-aligned.
            i = min(range(len(mids)), key=lambda i: abs(mids[i] - mid))
            heads.setdefault(i, []).append(w[4])
    colname = {i: " ".join(v) for i, v in heads.items()}
    # Row labels: words left of the class column between blocks.
    rows, prices = [], {}
    prev = top - 1e9
    label_top = ist + 4
    for bi, b in enumerate(blocks):
        lo = max(prev, label_top if bi == 0 else prev)
        hi = b[-1][0] + 2
        lab = [w for w in ws if w[2] < cx - 1 and lo < (w[1] + w[3]) / 2 <= hi and w[4] not in ("GİRİŞ", "GİŞELERİ", "İSTASYON") and not DIST.match(w[4]) and w[4] != "km"]
        prev = hi
        name = " ".join(w[4] for _, l in lines(lab) for w in l)
        rows.append(name)
        for c in b:
            for v in c[3]:
                i = col(v[2])
                if i is None:
                    raise ValueError(f"{name}: value {v[4]} in no column")
                prices.setdefault((name, i), {})[c[1]] = float(v[4].replace(".", "").replace(",", "."))
    ri = {n: k for k, n in enumerate(rows)}
    return rows, [colname.get(i, "") for i in range(len(centers))], {(ri[r], i): p for (r, i), p in prices.items()}


def matrix(path):
    """(row names, column header names, {(row index, column index): {class: TL}})."""
    found = [m for m in (page_matrix(ws) for ws in words(path)) if m[0]]
    if len(found) != 1:
        raise ValueError(f"{path}: {len(found)} pages with a matrix")
    return found[0]
