"""Reads the Serbian toll decision's price tables out of an issue of the
Official Gazette (Službeni glasnik RS, as the state's legal information
system serves it: its tables are scans, a page each or a table each) into
matrices.

The Odluka o visini posebne naknade za upotrebu javnog puta, njegovog dela
i putnog objekta (putarina) prints, for each characteristic motorway
section ("Деоница ..."), one matrix per vehicle category (IA, I, II, III,
IV in that order; some sections start at I): the toll in RSD from each
station (row) to each other (column). Only categories III and IV are kept
(the section's last two matrices, checked: IV is about twice III).

Each table's grid is found from its ruling lines: a table spans the rows
its column rules cross, and a band as tall as a header starts the next
table. A table printed across the page (or upside down) is turned upright
first (the orientation in which the table is square and its first column reads as
Cyrillic words). Station names are read with Tesseract's Serbian (Cyrillic)
model; each price cell is read as digits four ways (the grey scan at
three scales, and binarised with Otsu). A matrix is symmetric, so every
price is printed twice: a pair's
price is the value most of the six readings give, kept only when both
cells' readings agree on it (more than half the readings, and each cell
has it at least once). Where they don't, category IV, about twice III,
decides: the one pair of values both cells' readings hold whose ratio is
between 1.85 and 2.15 (1.6 and 2.5 under 300 RSD). A shaded or hatched cell (no
price: the pair isn't a trip, e.g. Novi Sad north towards Belgrade) has
none. The others are listed as unread and left out.

Usage: python3 gazette_ocr.py issue.pdf out.json
       python3 gazette_ocr.py --digest issue.pdf   (the issue's content digest,
       which out.json records)
Needs tesseract with the srp language, opencv, pytesseract, pymupdf.
"""
import difflib, hashlib, json, os, re, sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import cv2
import fitz
import numpy as np
import pytesseract

# One thread a Tesseract call: the cells are read in parallel processes
# (Tesseract's own threads would only contend with them).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
TESS = os.environ.get("TESSDATA_DIR")
TESS = f"--tessdata-dir {TESS}" if TESS else ""


def scans(doc, pno):
    """The page's table scans in reading order (down the left column, then
    the right), each at three times its own resolution: the gazette prints a
    page of tables as one scan, or each table as a scan of its own."""
    page = doc[pno]
    out = []
    for x in page.get_images(full=True):
        rects = page.get_image_rects(x[0])
        if x[2] < 300 or x[3] < 150 or not rects:
            continue
        im = cv2.imdecode(np.frombuffer(doc.extract_image(x[0])["image"], np.uint8), cv2.IMREAD_GRAYSCALE)
        key = (rects[0].x0 > page.rect.width / 2 - 20, rects[0].y0)
        out.append((key, cv2.resize(im, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)))
    return [im for _, im in sorted(out, key=lambda t: t[0])]


def groups(vals, gap=4):
    out = []
    for x in vals:
        if out and x - out[-1][-1] <= gap:
            out[-1].append(x)
        else:
            out.append([x])
    return [int(np.mean(g)) for g in out]


def rules(img):
    bw = cv2.adaptiveThreshold(255 - img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    h = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (img.shape[1] // 8, 1)))
    v = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)))
    return h, v


def tables_of(img):
    """Each table on the image: (top, row rules, column rules).

    A table spans the rows its column rules cross; tables printed one under
    the other are told apart by the gap where no column rule runs, and a
    table whose bottom or top rule didn't print ends or starts where its
    column rules do."""
    h, v = rules(img)
    ys = groups([y for y in range(h.shape[0]) if h[y].sum() > 255 * img.shape[1] * 0.3])
    on = (v > 0).sum(axis=1) >= 3
    spans, y, n = [], 0, len(on)
    while y < n:
        if not on[y]:
            y += 1
            continue
        s = y
        while y < n:
            if on[y]:
                y += 1
                continue
            g = y
            while g < n and not on[g] and g - y < 12:
                g += 1
            if g < n and on[g]:
                y = g
                continue
            break
        spans.append((s, y))
    res = []
    for s, e in spans:
        run = [y for y in ys if s - 10 <= y <= e + 10]
        if len(run) < 2 and e - s < 200:
            continue
        if not run or run[-1] < e - 10:
            run.append(e)
        if run[0] > s + 10:
            run.insert(0, s)
        # Tables printed with no gap between them: a band as tall as a header
        # (several rows tall) starts the next table.
        bands = [b - a for a, b in zip(run[1:], run[2:])]
        row = sorted(bands)[len(bands) // 2] if bands else 0
        cut = [0] + [k + 1 for k, b in enumerate(bands) if k and b > 3.5 * row] + [len(run) - 1]
        for a, b in zip(cut, cut[1:]):
            got = table_of(v, run[a:b + 1])
            if got:
                res.append(got)
    return res


def table_of(v, run):
    """A table's (top, row rules, column rules) from its horizontal rules."""
    if len(run) < 3:
        return None
    top, rows = run[0], run[1:]
    gaps = sorted(b - a for a, b in zip(rows, rows[1:]))
    if gaps:
        row = gaps[len(gaps) // 2]
        # A rule inside the header (under the title): the header ends at the
        # rule under its tall band.
        while len(rows) > 2 and rows[1] - rows[0] > 2.5 * row:
            rows = rows[1:]
        # A rule right under another (a double line, or the column rules
        # running on past the bottom rule) is the same rule.
        rows = [y for k, y in enumerate(rows) if k == 0 or y - rows[k - 1] > 0.7 * row]
        # Rows are all as tall: a band two or three rows tall is rows whose
        # rule didn't come out (beside a shaded row).
        out = rows[:1]
        for a, b in zip(rows, rows[1:]):
            k = round((b - a) / row)
            if k in (2, 3) and abs((b - a) / k - row) < 0.15 * row:
                out += [round(a + (b - a) * i / k) for i in range(1, k)]
            out.append(b)
        rows = out
    if len(rows) < 2:
        return None
    band = v[rows[0] + 5:rows[-1] - 5]
    cover = band.sum(axis=0) / 255 / max(1, band.shape[0])
    # Column rules run the table's height; one beside shaded cells comes out
    # in part: the table is square (a column per station besides the names).
    # A double line (the table's outer border) is one rule.
    def columns(least):
        xs = groups([x for x in range(band.shape[1]) if cover[x] > least])
        widths = sorted(b - a for a, b in zip(xs, xs[1:]))
        return [x for k, x in enumerate(xs) if k == 0 or x - xs[k - 1] > widths[len(widths) // 2] / 2] if widths else xs
    def edged(xs):
        # A table cut at the scan's edge has no rule there: the edge is its border.
        if len(xs) < 3 or len(xs) - 2 != len(rows) - 2:
            return xs
        width = sorted(b - a for a, b in zip(xs, xs[1:]))[(len(xs) - 1) // 2]
        if band.shape[1] - 1 - xs[-1] > 0.6 * width:
            return xs + [band.shape[1] - 1]
        if xs[0] > 0.6 * width:
            return [0] + xs
        return xs
    for least in (0.6, 0.45, 0.3):
        xs = edged(columns(least))
        if len(xs) - 2 == len(rows) - 1:
            break
    else:
        xs = columns(0.6)
    return (top, rows, xs) if len(xs) >= 3 else None


def text(img):
    if img.size == 0 or min(img.shape) < 5:
        return ""
    return re.sub(r"\s+", " ", pytesseract.image_to_string(img, lang="srp", config=TESS + " --psm 6")).strip()


def confidence(img):
    """Tesseract's mean word confidence reading the image as Serbian text."""
    if img.size == 0 or min(img.shape) < 5:
        return 0
    d = pytesseract.image_to_data(img, lang="srp", config=TESS + " --psm 6", output_type=pytesseract.Output.DICT)
    cs = [float(x) for x, w in zip(d["conf"], d["text"]) if w.strip() and float(x) >= 0]
    return sum(cs) / len(cs) if cs else 0


def digits(cell):
    """A price cell's readings: four ways of reading the digits (the grey
    scan at three scales, and binarised with Otsu)."""
    _, bw = cv2.threshold(cell, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out = []
    for im in (cell, cv2.resize(cell, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
               cv2.resize(cell, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA), bw):
        im = cv2.copyMakeBorder(im, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        s = pytesseract.image_to_string(im, lang="eng", config=f"{TESS} --psm 7 -c tessedit_char_whitelist=0123456789.").strip()
        ok = re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})*", s) or re.fullmatch(r"[1-9]\d{1,4}", s)
        out.append(int(s.replace(".", "")) if ok else None)
    return out


CYRILLIC = re.compile(r"[а-яђјљњћџ]{3,}", re.I)


def upright(img):
    """The image turned so its tables' station names read (a table printed
    across the page is turned): (image, its tables), or None. Turned right,
    a table is square (a row per station, a column per station besides the
    names) and its first column reads as Cyrillic words."""
    best = None
    for k in (0, 3, 1, 2):
        im = np.ascontiguousarray(np.rot90(img, k)) if k else img
        ts = tables_of(im)
        if not ts:
            continue
        top, rows, xs = ts[0]
        names = text(im[rows[0] + 4:rows[-1] - 4, xs[0] + 4:xs[1] - 4])
        cyrillic = sum(map(len, CYRILLIC.findall(names))) / (len(rows) - 1)
        score = (cyrillic >= 3, len(rows) - 1 == len(xs) - 2, cyrillic)
        if best is None or score > best[0]:
            best = (score, im, ts)
    return (best[1], best[2]) if best and best[0][0] else None


def read_cells(args):
    """Each cell's readings and whether it is shaded (no price)."""
    img, rows, xs = args
    out = []
    for a, b in zip(rows, rows[1:]):
        row = []
        for c, d in zip(xs[1:], xs[2:]):
            cell = img[a + 4:b - 3, c + 4:d - 3]
            # Shaded: even its lightest pixels are grey (a white cell's, around
            # its digits, are white), or hatched (half of it dark; digits are
            # far less).
            shaded = float(np.percentile(cell, 90)) < 200 or float((cell < 128).mean()) > 0.3
            row.append({"reads": [] if shaded else digits(cell), "shaded": shaded})
        out.append(row)
    return out


def ratio_ok(v3, v4):
    lo, hi = (1.6, 2.5) if v3 < 300 else (1.85, 2.15)
    return lo <= v4 / v3 <= hi


def resolve(c3, c4, n):
    """A pair's III and IV prices from both cells' readings in both matrices:
    each the value most readings give when that's more than half of them
    and both cells have it; else, from the values both cells have, the one
    pair of III and IV whose ratio fits."""
    prices3, prices4, unread = {}, {}, []
    for i in range(n):
        for j in range(i + 1, n):
            cells = {3: (c3[i][j], c3[j][i]), 4: (c4[i][j], c4[j][i])}
            if all(x["shaded"] for k in cells for x in cells[k]):
                continue
            pick, both = {}, {}
            for k, (a, b) in cells.items():
                ra, rb = [x for x in a["reads"] if x], [x for x in b["reads"] if x]
                votes = Counter(ra + rb)
                both[k] = [v for v, _ in votes.most_common() if v in ra and v in rb]
                v, cnt = votes.most_common(1)[0] if votes else (None, 0)
                if v is not None and cnt > (len(a["reads"]) + len(b["reads"])) / 2 and v in ra and v in rb:
                    pick[k] = v
            if 3 in pick and 4 in pick and not ratio_ok(pick[3], pick[4]):
                pick = {}
            if not (3 in pick and 4 in pick):
                combos = {(v3, v4) for v3 in ([pick[3]] if 3 in pick else both[3]) for v4 in ([pick[4]] if 4 in pick else both[4]) if ratio_ok(v3, v4)}
                if len(combos) == 1:
                    pick[3], pick[4] = next(iter(combos))
            key = f"{i}|{j}"
            if 3 in pick:
                prices3[key] = pick[3]
            if 4 in pick:
                prices4[key] = pick[4]
            if 3 not in pick or 4 not in pick:
                unread.append([i, j, [x["reads"] for x in cells[3]], [x["reads"] for x in cells[4]], sorted(pick)])
    return prices3, prices4, unread


def tables_in(pdf, doc, first):
    """The decision's tables, from its first page up to the next page with
    no table scans."""
    found, pno = [], first
    while pno < len(doc):
        ims = scans(doc, pno)
        if not ims:
            # A page of text after the tables ends them.
            if found:
                break
            pno += 1
            continue
        for k, img in enumerate(ims):
            up = upright(img)
            if up is None:
                # A picture that isn't a table (a logo, a signature): a
                # matrix missed would show in the checks of each section.
                print(f"{pdf}: page {pno + 1}, scan {k + 1}: no table", file=sys.stderr)
                continue
            im, ts = up
            for top, rows, xs in ts:
                # A matrix: a row per station and a column per station besides the names.
                if len(rows) < 4 or len(rows) - 1 != len(xs) - 2:
                    continue
                title = text(im[top + 4:rows[0] - 4, xs[0] + 4:xs[1] - 4])
                section = re.sub(r"\s*[–—-]+\s*", "–", re.split(r"\s(?:\S+\s)?категорија", title)[0]).strip()
                labels = [text(im[a + 4:b - 4, xs[0] + 4:xs[1] - 4]) for a, b in zip(rows, rows[1:])]
                found.append({"page": pno + 1, "section": section, "labels": labels, "img": im, "rows": rows, "xs": xs})
        pno += 1
    return found


def same(a, b):
    """Two tables' station names alike: the names, row by row, read about the
    same (a scan's names can read badly; another section's are different)."""
    norm = lambda s: re.sub(r"[^а-яђјљњћџ]", "", s.lower())
    return len(a["labels"]) == len(b["labels"]) and sum(
        difflib.SequenceMatcher(None, norm(x), norm(y)).ratio() for x, y in zip(a["labels"], b["labels"])) / len(a["labels"]) > 0.5


def sections_of(pdf, found):
    """The sections in order, each with its matrices (consecutive tables with
    the same stations); III and IV are its last two."""
    sections = []
    for t in found:
        if sections and any(same(t, u) for u in sections[-1]["tables"]):
            sections[-1]["tables"].append(t)
        else:
            sections.append({"section": t["section"], "tables": [t]})
    # A lone table isn't a section's (a section prints a matrix per
    # category): it is passed over, and a section it should have been
    # missing shows in the tables built (tools/rs/gazette.py).
    for s in sections:
        if len(s["tables"]) < 2:
            print(f"{pdf}: {s['section']!r} (page {s['tables'][0]['page']}): one matrix, passed over", file=sys.stderr)
    return [s for s in sections if len(s["tables"]) >= 2]


def digest(pdf):
    """The issue's content (its pages' text and images), so a copy of the
    same issue the server sent again with other bytes (a new file date, say)
    isn't read again."""
    doc = fitz.open(pdf)
    h = hashlib.sha256()
    for p in doc:
        h.update(p.get_text().encode())
        for x in p.get_images(full=True):
            h.update(doc.extract_image(x[0])["image"])
    return h.hexdigest()


def main(pdf, out):
    doc = fitz.open(pdf)
    # The amendment's page: it replaces the decision's paragraph 1 (the
    # tables "by vehicle category and characteristic motorway section").
    norm = lambda p: re.sub(r"\s+", " ", p.get_text())
    first = next((i for i, p in enumerate(doc) if "Одлуке о висини посебне накнаде" in norm(p) and "путарина" in norm(p)
                  and "карактеристичне деонице ауто-пута" in norm(p)), None)
    if first is None:
        sys.exit(f"{pdf}: the toll decision isn't in this issue")
    head = re.sub(r"\s+", " ", doc[first].get_text())
    found = tables_in(pdf, doc, first)
    if os.environ.get("RS_GAZETTE_DRY") == "2":
        for t in found:
            print(t["page"], len(t["labels"]), t["section"][:40], t["labels"])
    sections = sections_of(pdf, found)
    if os.environ.get("RS_GAZETTE_DRY"):
        for s in sections:
            print(s["section"], [t["page"] for t in s["tables"]], len(s["tables"][0]["labels"]), s["tables"][0]["labels"])
        return
    json.dump(read(pdf, head, sections), open(out, "w"), ensure_ascii=False, indent=1)


def read(pdf, head, sections):
    """Each section's III and IV prices, read and checked."""
    wanted = [(s, s["tables"][-2], "III") for s in sections] + [(s, s["tables"][-1], "IV") for s in sections]
    with ProcessPoolExecutor() as pool:
        cells = list(pool.map(read_cells, [(t["img"], t["rows"], t["xs"]) for _, t, _ in wanted]))
    result = {"pdf": os.path.basename(pdf), "digest": digest(pdf), "decision": head[:2000], "sections": []}
    for k, s in enumerate(sections):
        t3, t4 = s["tables"][-2], s["tables"][-1]
        p3, p4, unread = resolve(cells[k], cells[len(sections) + k], len(t3["labels"]))
        # IV is about twice III.
        r = sorted(p4[x] / p3[x] for x in p4 if x in p3)
        if not r or not 1.8 < r[len(r) // 2] < 2.2:
            sys.exit(f"{pdf}: {s['section']}: the last two matrices aren't III and IV (IV/III {r[len(r) // 2] if r else None})")
        # Each station's name as every matrix of the section reads it (the
        # most common reading first).
        readings = [[x for x, _ in Counter(t["labels"][i].strip() for t in s["tables"] if t["labels"][i].strip()).most_common()]
                    for i in range(len(t3["labels"]))]
        result["sections"].append({"section": s["section"], "matrices": len(s["tables"]), "pages": [t3["page"], t4["page"]],
                                   "stations": [r[0] if r else "" for r in readings], "readings": readings,
                                   "III": p3, "IV": p4, "unread": unread})
        print(f"{s['section']}: {len(t3['labels'])} stations, III {len(p3)} and IV {len(p4)} pairs read, {len(unread)} pairs not wholly")
    return result


if __name__ == "__main__":
    if sys.argv[1] == "--digest":
        print(digest(sys.argv[2]))
    else:
        main(*sys.argv[1:])
