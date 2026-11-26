"""Tests build.py's Hungarian rule on a small OSM file: only the toll
sections' ways (relations tagged ref:HU:edid), their other carriageways
and the gaps where the annex runs on count; the road between two sections
the annex doesn't join isn't tolled; a road whose sections OSM lacks is
tolled by its ref, but not inside Budapest unless it has a section there.

Usage: python3 test_hu.py
"""
import gzip, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

# Along latitude 47.5 from 19.30° E (1 km is about 0.0132° of longitude).
KM = 1 / (111.32 * 0.6756)
LAT, LON0 = 47.5, 19.30


def osm(path, areas):
    nodes, ways, rels = [], [], []
    nid = [0]

    def line(x0, x1, dy=0.0, steps=10):
        ids = []
        for i in range(steps + 1):
            nid[0] += 1
            x = LON0 + (x0 + (x1 - x0) * i / steps) * KM
            nodes.append(f'<node id="{nid[0]}" version="1" lat="{LAT + dy:.7f}" lon="{x:.7f}"/>')
            ids.append(nid[0])
        return ids

    def way(wid, ids, **tags):
        nds = "".join(f'<nd ref="{i}"/>' for i in ids)
        tg = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        ways.append(f'<way id="{wid}" version="1">{nds}{tg}</way>')

    way(1, line(0, 3), highway="primary", ref="3")                    # section 3u22k810m (22+810 - 25+058)
    way(2, line(0, 3, dy=0.0002), highway="primary", ref="3")         # its other carriageway, 22 m away
    way(3, line(3, 5), highway="primary", ref="3")                    # 3u25k058m, missing in OSM's relations
    way(4, line(5, 8), highway="primary", ref="3")                    # section 3u25k636m (25+636 - 27+430)
    way(5, line(-4, -1), highway="primary", ref="3")                  # between 3u17k534m and 3u22k810m: not in the annex
    way(7, line(-5, -4), highway="primary", ref="3")                  # section 3u17k534m (17+534 - 18+428)
    way(8, line(-1, 0), highway="primary", ref="3")                   # ... it too, up to 3u22k810m
    way(6, line(0, 6, dy=0.05), highway="motorway", ref="M1")         # in no section, OSM lacking M1's: by ref
    way(9, line(-10, -7), highway="primary", ref="3")                 # inside Budapest
    way(10, line(-11, -8, dy=0.05), highway="motorway", ref="M1")     # inside Budapest
    way(11, line(-11, -10, dy=-0.05), highway="motorway", ref="M0")   # section M0u0k0m, inside Budapest
    way(12, line(-10, -8, dy=-0.05), highway="motorway", ref="M0")    # M0 by ref there: tolled
    # Road 21, 2.2 km north: a dual carriageway (12 m apart) whose gap
    # 21u7k310m OSM's relations lack on both carriageways, then a single one
    # whose gap 21u11k1015m has a roundabout without the ref in it.
    D, W = 0.02, 0.000108
    way(20, line(20, 21, dy=D), highway="primary", ref="21")          # section 21u6k640m
    way(21, line(20, 21, dy=D + W), highway="primary", ref="21")      # section 21u6k640m
    way(22, line(21, 24, dy=D), highway="primary", ref="21")          # gap, one carriageway
    way(23, line(21, 24, dy=D + W), highway="primary", ref="21")      # gap, the other
    way(24, line(24, 26, dy=D), highway="primary", ref="21")          # section 21u10k715m
    way(25, line(24, 26, dy=D + W), highway="primary", ref="21")      # section 21u10k715m
    way(26, line(26, 27.48, dy=D), highway="primary", ref="21")       # gap, to the roundabout
    ring = []
    for i in range(12):
        import math
        nid[0] += 1
        a = 2 * math.pi * i / 12
        nodes.append(f'<node id="{nid[0]}" version="1" lat="{LAT + D + 0.00018 * math.sin(a):.7f}" lon="{LON0 + (27.5 + 0.02 * math.cos(a)) * KM:.7f}"/>')
        ring.append(nid[0])
    way(27, ring + ring[:1], highway="primary", junction="roundabout")
    way(28, line(27.52, 29, dy=D), highway="primary", ref="21")       # gap, from the roundabout
    way(29, line(29, 31, dy=D), highway="primary", ref="21")          # section 21u14k263m
    secs = (("3u22k810m", [1]), ("3u25k636m", [4]), ("3u17k534m", [7]), ("M0u0k0m", [11]),
            ("21u6k640m", [20, 21]), ("21u10k715m", [24, 25]), ("21u14k263m", [29]))
    for rid, (edid, ws) in enumerate(secs, 1):
        members = "".join(f'<member type="way" ref="{w}" role=""/>' for w in ws)
        rels.append(f'<relation id="{rid}" version="1">{members}<tag k="type" v="route"/><tag k="ref:HU:edid" v="{edid}"/></relation>')
    open(path, "w").write('<?xml version="1.0"?><osm version="0.6">' + "".join(nodes + ways + rels) + "</osm>")
    # Budapest: from 12 to 6 km west, 0.1° either side.
    ring = [(-12, -0.1), (-6, -0.1), (-6, 0.1), (-12, 0.1)]
    ns = "".join(f'<node id="{9000 + i}" version="1" lat="{LAT + dy:.7f}" lon="{LON0 + x * KM:.7f}"/>' for i, (x, dy) in enumerate(ring))
    w = '<way id="9000" version="1">' + "".join(f'<nd ref="{9000 + i}"/>' for i in (0, 1, 2, 3, 0)) + "</way>"
    r = ('<relation id="9000" version="1"><member type="way" ref="9000" role="outer"/><tag k="type" v="boundary"/>'
         '<tag k="boundary" v="administrative"/><tag k="admin_level" v="6"/><tag k="name" v="Budapest"/></relation>')
    open(areas, "w").write('<?xml version="1.0"?><osm version="0.6">' + ns + w + r + "</osm>")


def run(covered):
    """nat and mw km with build.COVERED at covered (0: every road's sections
    taken as in OSM, so only sections, twins and gaps count)."""
    d = tempfile.mkdtemp()
    src, dst, areas = os.path.join(d, "hu.osm"), os.path.join(d, "hu.json.gz"), os.path.join(d, "areas.osm")
    osm(src, areas)
    build.COVERED = covered
    build.main("HU", src, dst, areas)
    out = json.load(gzip.open(dst))
    km = lambda lines: sum(sum(((l[i + 2] - l[i]) ** 2 + (l[i + 3] - l[i + 1]) ** 2) ** 0.5 for i in range(0, len(l) - 2, 2)) for l in lines) / 1e5 / KM
    for f in (src, dst, areas):
        os.remove(f)
    os.rmdir(d)
    return km(out["nat"]), km(out["mw"]), len(out["natf"]) == len(out["nat"])


def main():
    sections = 12 + 6 + 6 + 2 + 2.96  # road 3: 3 + 3 + 1, the other carriageway 3, the gap 2; road 21: 2 x 1 + 2 x 2 + 2, its dual gap 2 x 3, the gap across the roundabout 2.96
    nat, mw, shares = run(0.9)
    ok = abs(nat - sections) < 0.2 and abs(mw - 9) < 0.2 and shares
    print(f"nat {nat:.2f} km (want {sections:.2f}), mw {mw:.2f} km (want 9: M1 by ref outside Budapest 6, M0's section 1 and by ref in Budapest 2)")
    nat, mw, shares = run(0)
    ok = ok and abs(nat - sections) < 0.2 and abs(mw - 1) < 0.2 and shares
    print(f"every road covered: nat {nat:.2f} km (want {sections:.2f}: the gaps found as gaps), mw {mw:.2f} km (want 1: M0's section)")
    if not ok:
        sys.exit("test_hu: FAILED")
    print("test_hu: ok")


if __name__ == "__main__":
    main()
