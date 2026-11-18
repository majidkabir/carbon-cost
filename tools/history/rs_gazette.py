"""Reads the Serbian toll decision's price tables out of an issue of the
Official Gazette (Službeni glasnik RS, as the state's legal information
system serves it: one scanned image per page) into matrices.

The Odluka o visini posebne naknade za upotrebu javnog puta, njegovog dela
i putnog objekta (putarina) prints, for each characteristic motorway
section ("Деоница ..."), one matrix per vehicle category (IA, I, II, III,
IV in that order; some sections start at I): the toll in RSD from each
station (row) to each other (column). Only categories III and IV are kept
(the section's last two matrices, checked: IV is about twice III).

Each table's grid is found from its ruling lines; a table printed across
the page is turned upright first (the orientation whose title cell reads
"Деоница"). Station names are read with Tesseract's Serbian (Cyrillic)
model; each price cell is read as digits three ways (the scan upscaled
three times, binarised with Otsu, read whole and as a single line at two
scales). A matrix is symmetric, so every price is printed twice: a pair's
price is the value most of the six readings give, kept only when both
cells' readings agree on it (a strict majority of the six, and each cell
has it at least once). Where they don't, category IV, about twice III,
decides: the one pair of values both cells' readings hold whose ratio is
between 1.85 and 2.15 (1.6 and 2.5 under 300 RSD). A shaded cell (no
price: the pair isn't a trip, e.g. Novi Sad north towards Belgrade) has
none. The others are listed as unread and left out.

Usage: python3 rs_gazette.py issue.pdf out.json
Needs tesseract with the srp language, opencv, pytesseract, pymupdf.
"""
import json, os, re, sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import cv2
import fitz
import numpy as np
import pytesseract

TESS = os.environ.get("TESSDATA_DIR")
TESS = f"--tessdata-dir {TESS}" if TESS else ""


def page_img(doc, pno):
    """The page's scan at three times its own resolution (the gazette's
    tables are one image per page), else the page rendered at 300 dpi."""
    imgs = doc[pno].get_images(full=True)
    if len(imgs) == 1:
        raw = doc.extract_image(imgs[0][0])["image"]
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        return cv2.resize(im, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    pix = doc[pno].get_pixmap(dpi=300, colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


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
    """Each table on the image: (top, row rules, column rules)."""
    h, v = rules(img)
    ys = groups([y for y in range(h.shape[0]) if h[y].sum() > 255 * img.shape[1] * 0.3])
    # A band between two rules is inside a table when column rules cross it.
    inside = [v[a + 3:b - 3].sum() > 255 * (b - a - 6) * 3 for a, b in zip(ys, ys[1:])]
    res, i = [], 0
    while i < len(inside):
        if not inside[i]:
            i += 1
            continue
        j = i
        while j < len(inside) and inside[j]:
            j += 1
        top, rows = ys[i], ys[i + 1:j + 1]
        band = v[rows[0] + 5:rows[-1] - 5]
        xs = groups([x for x in range(band.shape[1]) if band[:, x].sum() > 255 * band.shape[0] * 0.6])
        # A header whose top rule didn't come out: the band above the first
        # rule is a row like the others, and the header starts where the
        # column rules start.
        gaps = sorted(b - a for a, b in zip(rows, rows[1:]))
        if gaps and rows[0] - top < 1.5 * gaps[len(gaps) // 2] and len(xs) >= 3:
            starts = []
            for x in xs[1:]:
                col = v[:top, max(0, x - 3):x + 4].any(axis=1)
                y = top
                while y > 0 and col[y - 1]:
                    y -= 1
                starts.append(y)
            head = int(np.median(starts))
            if top - head > 1.5 * gaps[len(gaps) // 2]:
                rows, top = [top] + rows, head
        if len(rows) >= 2 and len(xs) >= 3:
            res.append((top, rows, xs))
        i = j
    return res


def text(img):
    return re.sub(r"\s+", " ", pytesseract.image_to_string(img, lang="srp", config=TESS + " --psm 6")).strip()


def digits(cell):
    """A price cell's readings: three ways of reading the digits."""
    _, bw = cv2.threshold(cell, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out = []
    for im, psm in ((bw, 7), (bw, 8), (cv2.resize(bw, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC), 7)):
        im = cv2.copyMakeBorder(im, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        s = pytesseract.image_to_string(im, lang="eng", config=f"{TESS} --psm {psm} -c tessedit_char_whitelist=0123456789.").strip()
        s = s.replace(".", "")
        out.append(int(s) if re.fullmatch(r"\d{2,5}", s) and not s.startswith("0") else None)
    return out


def upright(img):
    """The image turned so its tables' titles read: (image, its tables), or None."""
    for k in (0, 3, 1):
        im = np.ascontiguousarray(np.rot90(img, k)) if k else img
        ts = tables_of(im)
        if ts:
            top, rows, xs = ts[0]
            if "еоница" in text(im[top + 4:rows[0] - 4, xs[0] + 4:xs[1] - 4]):
                return im, ts
    return None


def read_cells(args):
    """Each cell's readings and whether it is shaded (no price)."""
    img, rows, xs = args
    out = []
    for a, b in zip(rows, rows[1:]):
        row = []
        for c, d in zip(xs[1:], xs[2:]):
            cell = img[a + 4:b - 3, c + 4:d - 3]
            # Shaded: even its lightest pixels are grey (a white cell's, around its digits, are white).
            shaded = float(np.percentile(cell, 90)) < 200
            row.append({"reads": [] if shaded else digits(cell), "shaded": shaded})
        out.append(row)
    return out


def ratio_ok(v3, v4):
    lo, hi = (1.6, 2.5) if v3 < 300 else (1.85, 2.15)
    return lo <= v4 / v3 <= hi


def resolve(c3, c4, n):
    """A pair's III and IV prices from both cells' readings in both matrices."""
    prices3, prices4, unread = {}, {}, []
    for i in range(n):
        for j in range(i + 1, n):
            cells = {3: (c3[i][j], c3[j][i]), 4: (c4[i][j], c4[j][i])}
            if all(x["shaded"] for k in cells for x in cells[k]):
                continue
            pick = {}
            both = {}
            for k, (a, b) in cells.items():
                ra, rb = [x for x in a["reads"] if x], [x for x in b["reads"] if x]
                votes = Counter(ra + rb)
                both[k] = [v for v, _ in votes.most_common() if v in ra and v in rb]
                v, cnt = votes.most_common(1)[0] if votes else (None, 0)
                if v is not None and cnt >= 4 and v in ra and v in rb:
                    pick[k] = v
            if 3 in pick and 4 in pick and ratio_ok(pick[3], pick[4]):
                prices3[f"{i}|{j}"], prices4[f"{i}|{j}"] = pick[3], pick[4]
                continue
            combos = [(v3, v4) for v3 in ([pick[3]] if 3 in pick else both[3]) for v4 in ([pick[4]] if 4 in pick else both[4]) if ratio_ok(v3, v4)]
            if len(combos) == 1:
                prices3[f"{i}|{j}"], prices4[f"{i}|{j}"] = combos[0]
            else:
                unread.append([i, j, [x["reads"] for x in cells[3]], [x["reads"] for x in cells[4]]])
    return prices3, prices4, unread


def main(pdf, out):
    doc = fitz.open(pdf)
    first = next((i for i, p in enumerate(doc) if "путарина" in p.get_text() and "Надзорни одбор Јавног предузећа" in p.get_text()
                  and "карактеристичне деонице ауто-пута" in p.get_text().replace("\n", " ")), None)
    if first is None:
        sys.exit(f"{pdf}: the toll decision isn't in this issue")
    head = re.sub(r"\s+", " ", doc[first].get_text())
    found, pno = [], first
    while pno < len(doc):
        up = upright(page_img(doc, pno))
        if up is None:
            if pno > first:
                break
            pno += 1
            continue
        im, ts = up
        for top, rows, xs in ts:
            title = text(im[top + 4:rows[0] - 4, xs[0] + 4:xs[1] - 4])
            section = re.sub(r"\s*[–—-]\s*", "–", re.split(r"\s(?:\S+\s)?категорија", title)[0]).strip()
            labels = [text(im[a + 4:b - 4, xs[0] + 4:xs[1] - 4]) for a, b in zip(rows, rows[1:])]
            found.append({"page": pno + 1, "section": section, "labels": labels, "img": im, "rows": rows, "xs": xs})
        pno += 1
    # The sections in order, each with its matrices; III and IV are its last two.
    sections = []
    for t in found:
        key = re.sub(r"[^а-яђјљњћџ]", "", t["section"].lower())[:20]
        if sections and sections[-1]["key"] == key and len(t["labels"]) == len(sections[-1]["tables"][0]["labels"]):
            sections[-1]["tables"].append(t)
        else:
            sections.append({"key": key, "section": t["section"], "tables": [t]})
    wanted = [(s, s["tables"][-2], "III") for s in sections] + [(s, s["tables"][-1], "IV") for s in sections]
    with ProcessPoolExecutor() as pool:
        cells = list(pool.map(read_cells, [(t["img"], t["rows"], t["xs"]) for _, t, _ in wanted]))
    result = {"pdf": os.path.basename(pdf), "decision": head[:2000], "sections": []}
    for k, s in enumerate(sections):
        t3, t4 = s["tables"][-2], s["tables"][-1]
        p3, p4, unread = resolve(cells[k], cells[len(sections) + k], len(t3["labels"]))
        # IV is about twice III.
        r = sorted(p4[x] / p3[x] for x in p4 if x in p3)
        if not r or not 1.8 < r[len(r) // 2] < 2.2:
            sys.exit(f"{pdf}: {s['section']}: the last two matrices aren't III and IV (IV/III {r[len(r) // 2] if r else None})")
        result["sections"].append({"section": s["section"], "matrices": len(s["tables"]), "pages": [t3["page"], t4["page"]],
                                   "stations": t3["labels"], "III": p3, "IV": p4, "unread": unread})
        print(f"{s['section']}: {len(t3['labels'])} stations, {len(p3)} pairs read, {len(unread)} not")
    json.dump(result, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
