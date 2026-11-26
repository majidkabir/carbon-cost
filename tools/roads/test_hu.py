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
    for rid, (edid, w) in enumerate((("3u22k810m", 1), ("3u25k636m", 4), ("3u17k534m", 7), ("M0u0k0m", 11)), 1):
        rels.append(f'<relation id="{rid}" version="1"><member type="way" ref="{w}" role=""/>'
                    f'<tag k="type" v="route"/><tag k="ref:HU:edid" v="{edid}"/></relation>')
    open(path, "w").write('<?xml version="1.0"?><osm version="0.6">' + "".join(nodes + ways + rels) + "</osm>")
    # Budapest: from 12 to 6 km west, 0.1° either side.
    ring = [(-12, -0.1), (-6, -0.1), (-6, 0.1), (-12, 0.1)]
    ns = "".join(f'<node id="{9000 + i}" version="1" lat="{LAT + dy:.7f}" lon="{LON0 + x * KM:.7f}"/>' for i, (x, dy) in enumerate(ring))
    w = '<way id="9000" version="1">' + "".join(f'<nd ref="{9000 + i}"/>' for i in (0, 1, 2, 3, 0)) + "</way>"
    r = ('<relation id="9000" version="1"><member type="way" ref="9000" role="outer"/><tag k="type" v="boundary"/>'
         '<tag k="boundary" v="administrative"/><tag k="admin_level" v="6"/><tag k="name" v="Budapest"/></relation>')
    open(areas, "w").write('<?xml version="1.0"?><osm version="0.6">' + ns + w + r + "</osm>")


def main():
    d = tempfile.mkdtemp()
    src, dst, areas = os.path.join(d, "hu.osm"), os.path.join(d, "hu.json.gz"), os.path.join(d, "areas.osm")
    osm(src, areas)
    build.main("HU", src, dst, areas)
    out = json.load(gzip.open(dst))
    km = lambda lines: sum(sum(((l[i + 2] - l[i]) ** 2 + (l[i + 3] - l[i + 1]) ** 2) ** 0.5 for i in range(0, len(l) - 2, 2)) for l in lines) / 1e5 / KM
    nat, mw = km(out["nat"]), km(out["mw"])
    ok = abs(nat - 12) < 0.2 and abs(mw - 9) < 0.2 and len(out["natf"]) == len(out["nat"])
    print(f"nat {nat:.2f} km (want 12: sections 3 + 3 + 1, the other carriageway 3, the gap 2), mw {mw:.2f} km (want 9: M1 by ref outside Budapest 6, M0's section 1 and by ref in Budapest 2)")
    for f in (src, dst, areas):
        os.remove(f)
    os.rmdir(d)
    if not ok:
        sys.exit("test_hu: FAILED")
    print("test_hu: ok")


if __name__ == "__main__":
    main()
