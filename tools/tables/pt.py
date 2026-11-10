"""Builds the Portuguese motorway toll table from IMT's 2026 toll rates
per lanço (fetch.py's pt-imt-taxas.html, "Taxas de Portagem de 2026":
each section between two junctions with its length and class 1-4 rate)
and the motorways in OpenStreetMap (the workflow's pt-osm.geojsonseq:
motorway ways with their refs, motorway junctions, from Geofabrik's
Portugal extract; its date in pt-osm-timestamp.txt).

Usage: python3 pt.py fetched/ out-dir -> out-dir/pt-<year>-01-01.json

A trip on a Portuguese motorway pays the lanços it drives (the
concession's per-km tariff over the trip plus IVA, rounded per lanço in
IMT's table; a ticket over several lanços may differ by a few cents).
Each lanço becomes a toll point in its middle, charged either way.

OSM names too few junctions to place lanços by name, so they're placed
by length: a motorway's lanços whose names chain ("X / Y", "Y / Z") are
laid along the longest carriageway of its ways (the ref in OSM), their
ends at motorway junction nodes, the choice (either direction) whose
section lengths best match IMT's (dynamic programming). A run of lanços
is kept when it has three or more, or when an end named after an
interchange ("A1/A10", "(A1/A9)") lies within 1.5 km of that other
motorway; a run where such an end doesn't is dropped. A lanço is kept
when its placed length is within 0.6 km or 10% of IMT's. Its toll point
is at its middle on that carriageway, and at the nearest point of the
other carriageway (within 250 m).

Classes (IMT's report on tolls, after the concession bases): class 2 two
axles (1.1 m or higher at the front axle), 3 three axles, 4 more than
three. Rates include IVA (the concession bases: "acrescido do IVA à taxa
em vigor"): 23%, divided out. The Lusoponte bridges (Ponte 25 de Abril,
Ponte Vasco da Gama) charge northbound only, at the 6% rate the IVA code
sets for the Tejo crossings in Lisbon; each is a toll point at its main
span, on the carriageway heading north.
"""
import html, json, math, os, re, sys
from collections import Counter, defaultdict

IVA, IVA_TEJO = 1.23, 1.06
CLASSES = [(2, 2, 1), (3, 3, 2), (4, 0, 3)]  # min axles, max axles, column (class 2, 3, 4)


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111.2 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111.2)


def length(c):
    return sum(km(c[i], c[i + 1]) for i in range(len(c) - 1))


def cells(r):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).replace("\xa0", " ").strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]


def lancos(path):
    t = open(path, encoding="utf-8").read()
    out = []
    for tb in re.findall(r"<table.*?</table>", t, flags=re.S):
        op = road = None
        for r in re.findall(r"<tr.*?</tr>", tb, flags=re.S):
            c = cells(r)
            if op is None:
                op = c[0]
                continue
            if len(c) >= 6 and all(re.fullmatch(r"\d+(,\d+)?", x) for x in c[-5:]):
                lead = c[:-5]
                m = re.match(r"^(A\s*\d+)", lead[0]) if lead else None
                if m:
                    road = m.group(1).replace(" ", "")
                out.append({"op": op, "road": road, "no": lead[-2] if len(lead) >= 2 else "", "name": lead[-1],
                            "km": float(c[-5].replace(",", ".")), "cl": [float(x.replace(",", ".")) for x in c[-4:]]})
    return out


def ends(name):
    """The lanço's two ends ("X / Y", "X – Y"), not splitting at a slash
    inside brackets or between road numbers ("A1/A10")."""
    depth, cut = 0, []
    for i, ch in enumerate(name):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch in "/–-":
            a, b = name[:i].rstrip(), name[i + 1:].lstrip()
            if ch in "/-" and re.search(r"(A|IP|IC|EN)\s*\d*$", a) and re.match(r"(A|IP|IC|EN)?\s*\d+", b) and not (ch == "/" and name[i - 1] == " " and name[i + 1] == " "):
                continue
            if ch == "-" and not (name[i - 1] == " " or name[i + 1] == " "):
                continue
            cut.append(i)
    if len(cut) != 1:
        return None
    return name[:cut[0]].strip(), name[cut[0] + 1:].strip()


def norm(x):
    return re.sub(r"[^a-z0-9]", "", x.lower())


def runs(ls):
    out = []
    for l in ls:
        e = ends(l["name"])
        if not e:
            continue
        l = dict(l, e=e)
        if out and norm(out[-1][-1]["e"][1]) == norm(e[0]):
            out[-1].append(l)
        else:
            out.append([l])
    return out


def chain(ws):
    """The longest path along the road's one-way ways."""
    nxt = defaultdict(list)
    for i, c in enumerate(ws):
        nxt[c[0]].append(i)
    indeg = Counter(c[-1] for c in ws)
    memo = {}

    def walk(i, depth=0):
        if i in memo:
            return memo[i]
        memo[i] = (length(ws[i]), [i])  # guards cycles
        best = (0.0, [])
        if depth < 5000:
            for j in sorted(nxt.get(ws[i][-1], [])):
                cand = walk(j, depth + 1)
                if cand[0] > best[0]:
                    best = cand
        memo[i] = (length(ws[i]) + best[0], [i] + best[1])
        return memo[i]

    sys.setrecursionlimit(20000)
    paths = [walk(i) for i in sorted(range(len(ws)), key=lambda i: ws[i][0]) if indeg[ws[i][0]] == 0]
    if not paths:
        return []
    _, p = max(paths, key=lambda x: (round(x[0], 6), -x[1][0]))
    pts = []
    for k in p:
        pts += ws[k] if not pts else ws[k][1:]
    return pts


def project(line, q):
    """(distance km, position km along the line) of the nearest point."""
    best, cum = (1e9, 0.0), 0.0
    cos = math.cos(math.radians(q[1]))
    for i in range(len(line) - 1):
        a, b = line[i], line[i + 1]
        ax, ay, bx, by = a[0] * cos * 111.2, a[1] * 111.2, b[0] * cos * 111.2, b[1] * 111.2
        qx, qy = q[0] * cos * 111.2, q[1] * 111.2
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        t = 0 if l2 == 0 else max(0.0, min(1.0, ((qx - ax) * dx + (qy - ay) * dy) / l2))
        d = math.hypot(ax + t * dx - qx, ay + t * dy - qy)
        if d < best[0]:
            best = (d, cum + t * math.sqrt(l2))
        cum += math.sqrt(l2)
    return best


def at(line, pos):
    """The point at pos km along the line, and the bearing there."""
    cum = 0.0
    for i in range(len(line) - 1):
        d = km(line[i], line[i + 1])
        if cum + d >= pos and d > 0:
            f = (pos - cum) / d
            a, b = line[i], line[i + 1]
            p = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
            brg = math.degrees(math.atan2((b[0] - a[0]) * math.cos(math.radians(a[1])), b[1] - a[1])) % 360
            return p, brg
        cum += d
    return line[-1], 0.0


def align(run, cand):
    """Ends at candidate positions, increasing, matching the lengths."""
    n, m, inf = len(run), len(cand), float("inf")
    f = [[inf] * m for _ in range(n + 1)]
    back = [[-1] * m for _ in range(n + 1)]
    f[0] = [0.0] * m
    for i in range(1, n + 1):
        L = run[i - 1]["km"]
        for j in range(m):
            for k in range(j):
                d = cand[j] - cand[k]
                if d > L * 1.6 + 3:
                    continue
                c = f[i - 1][k] + abs(d - L)
                if c < f[i][j]:
                    f[i][j], back[i][j] = c, k
    j = min(range(m), key=lambda j: f[n][j])
    cost, pos = f[n][j], [0.0] * (n + 1)
    pos[n] = cand[j]
    for i in range(n, 0, -1):
        j = back[i][j]
        pos[i - 1] = cand[j]
    return cost, pos


def classes(cl, vat):
    return [{"min_axles": lo, **({"max_axles": hi} if hi else {}), "rate": round(cl[col] / vat, 4)} for lo, hi, col in CLASSES]


def main(fetched, out):
    ls = lancos(os.path.join(fetched, "pt-imt-taxas.html"))
    ways, other, junc = defaultdict(list), defaultdict(list), []
    named = defaultdict(list)
    for line in open(os.path.join(fetched, "pt-osm.geojsonseq"), encoding="utf-8"):
        f = json.loads(line.strip("\x1e"))
        p, g = f["properties"], f["geometry"]
        if p.get("highway") == "motorway" and g["type"] == "LineString":
            c = [tuple(x) for x in g["coordinates"]]
            if p.get("oneway") == "-1":
                c = c[::-1]
            if p.get("name"):
                named[p["name"]].append(c)
            for r in (p.get("ref") or "").split(";"):
                r = r.replace(" ", "")
                if r:
                    (ways if p.get("oneway") in ("yes", "-1") else other)[r].append(c)
        elif p.get("highway") == "motorway_junction" and g["type"] == "Point":
            junc.append(tuple(g["coordinates"]))
    points, kept, dropped = [], 0, []
    year = re.search(r"Taxas de Portagem de (\d{4})", open(os.path.join(fetched, "pt-imt-taxas.html"), encoding="utf-8").read()).group(1)
    for road in sorted({l["road"] for l in ls if l["road"]}, key=lambda r: int(r[1:])):
        ws = ways[road] + other[road]
        line = chain(ways[road])
        if not line:
            dropped += [f"{road} {l['no']}" for l in ls if l["road"] == road]
            continue
        tot = length(line)
        js = sorted({round(pos, 3) for d, pos in (project(line, q) for q in junc) if d < 0.03})
        cand = sorted({0.0, round(tot, 3), *js})
        for run in runs([l for l in ls if l["road"] == road]):
            best = None
            for rev in (False, True):
                c = sorted(round(tot - x, 3) for x in cand) if rev else cand
                cost, pos = align(run, c)
                if best is None or cost < best[0]:
                    best = (cost, pos, rev)
            cost, pos, rev = best
            pts = [at(line, tot - x if rev else x)[0] for x in pos]
            # Ends named after an interchange must lie by that motorway.
            anchors, ok = 0, True
            for i, e in enumerate([run[0]["e"][0]] + [l["e"][1] for l in run]):
                for r in set(re.findall(r"A\s*(\d+)", e)):
                    r = "A" + r
                    if r == road or not (ways[r] or other[r]):
                        continue
                    d = min(project(w, pts[i])[0] for w in ways[r] + other[r])
                    anchors += 1
                    if d > 1.5:
                        ok = False
                        print(f"  {road} run {run[0]['no']}-{run[-1]['no']}: {e} is {d:.1f} km from {r}")
            if not ok or (len(run) < 3 and anchors == 0):
                dropped += [f"{road} {l['no']}" for l in run]
                continue
            for i, l in enumerate(run):
                a, b = pos[i], pos[i + 1]
                if abs((b - a) - l["km"]) > max(0.6, 0.1 * l["km"]):
                    dropped.append(f"{road} {l['no']}")
                    continue
                mid = (a + b) / 2
                p, _ = at(line, tot - mid if rev else mid)
                cls = classes(l["cl"], IVA)
                name = f"{road} {l['name']}"
                points.append({"name": name, "lat": round(p[1], 6), "lon": round(p[0], 6), "rate": 0, "classes": cls})
                # The other carriageway, if it's near.
                best2 = None
                for w in ws:
                    for q in w:
                        d = km(q, p)
                        if 0.01 < d < 0.25 and (best2 is None or d < best2[0]):
                            best2 = (d, q)
                if best2:
                    points.append({"name": name, "lat": round(best2[1][1], 6), "lon": round(best2[1][0], 6), "rate": 0, "classes": cls})
                kept += 1
            print(f"{road} {run[0]['no']}-{run[-1]['no']}: fit {cost:.2f} km over {len(run)} lanços{' (reversed)' if rev else ''}")
    # Lusoponte: northbound only, at the bridge's main span.
    for l in ls:
        if l["op"] != "Lusoponte":
            continue
        cs = [c for n, cc in named.items() if n == l["name"] for c in cc]
        north = [c for c in cs if c[-1][1] > c[0][1]]
        if not north:
            sys.exit(f"{l['name']}: no northbound way in OpenStreetMap")
        c = max(north, key=length)
        p, brg = at(c, length(c) / 2)
        points.append({"name": l["name"], "lat": round(p[1], 6), "lon": round(p[0], 6), "heading": round(brg, 1), "rate": 0,
                       "classes": classes(l["cl"], IVA_TEJO)})
        kept += 1
        print(f"{l['name']}: northbound at {p[1]:.5f},{p[0]:.5f} heading {brg:.0f}")
    print(f"{kept} lanços placed; dropped {len(dropped)}: {', '.join(dropped)}")
    osm = open(os.path.join(fetched, "pt-osm-timestamp.txt")).read().strip()[:10]
    tb = {
        "country": "PT", "currency": "EUR", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
        "osm_extract": osm,
        "name": "Portuguese motorway tolls (portagens)",
        "law": f"IMT, Taxas de Portagem de {year}: the toll of each lanço by class, set by the concession contracts and validated by IMT; class 2 (two axles, 1.1 m or higher at the front axle), 3 (three axles), 4 (more than three), excluding IVA (23%; 6% on the Lusoponte Tejo crossings, which charge northbound only). A trip pays each lanço it drives: each is a toll point in its middle, placed along the motorway by IMT's lengths at OpenStreetMap's junctions (extract of {osm}). {len(dropped)} lanços that couldn't be placed (branches, short runs, misfits) aren't charged. Only the concessions IMT's page lists (Brisa, Oeste, Brisal, Douro Litoral, Lusoponte, IP's A21).",
        "sources": [{"title": f"IMT: Taxas de Portagem de {year}", "url": "https://www.imt-ip.pt/rodoviario/infraestruturas-rodoviarias/rede-rodoviaria/taxas-de-portagem/"},
                    {"title": "Polígrafo: Lusoponte bridge tolls carry the reduced 6% IVA", "url": "http://poligrafo.sapo.pt/fact-check/portagens-das-pontes-25-de-abril-e-vasco-da-gama-tem-taxa-reduzida-6-de-iva-ao-contrario-do-resto-do-pais/"},
                    {"title": "Decreto-Lei n.º 294/97 (Brisa concession bases), consolidated: tolls plus IVA", "url": "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2008-168384077"},
                    {"title": "OpenStreetMap (Geofabrik extract), motorways", "url": "https://download.geofabrik.de/europe/portugal.html"}],
        "vehicles": "Trucks of two or more axles (classes 2 to 4)",
        "tolled_roads": "The lanços in IMT's table: A1, A2, A3, A4, A5, A6, A8, A9, A10, A12, A13, A14, A15, A17, A21, A32, A41, A43, and the Ponte 25 de Abril and Ponte Vasco da Gama.",
        "point_match_km": 0.05,
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"pt-{year}-01-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path)


if __name__ == "__main__":
    main(*sys.argv[1:])
