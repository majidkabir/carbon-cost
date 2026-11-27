"""Tests build.py's Bulgarian rule on a small OSM file: the class I and II
roads are tolled where their toll segments run (bgseg.py), found along
the road between their ends: not in the settlement between two segments,
across a roundabout without the road's ref, on each carriageway of a dual
road by its direction's segment (not by a U-turn from the other), on a road OSM tags as motorway (but not
where it has no segment), and on a ring road OSM gives no ref; a class II road with no segments isn't
tolled; motorways are.

Usage: python3 test_bg.py
"""
import gzip, json, math, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

# Along latitude 42.5 from 24.0° E (1 km is about 0.01218° of longitude).
KM = 1 / (111.32 * math.cos(math.radians(42.5)))
LAT, LON0 = 42.5, 24.0


def pt(x, dy=0.0):
    return LON0 + x * KM, LAT + dy


def osm(path):
    nodes, ways = {}, []

    def node(lon, lat):
        key = (round(lon, 7), round(lat, 7))
        if key not in nodes:
            nodes[key] = len(nodes) + 1
        return nodes[key]

    def way(wid, pts, **tags):
        ids = [node(*p) for p in pts]
        nds = "".join(f'<nd ref="{i}"/>' for i in ids)
        tg = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        ways.append(f'<way id="{wid}" version="1">{nds}{tg}</way>')

    line = lambda x0, x1, dy=0.0: [pt(x0 + (x1 - x0) * i / 20, dy) for i in range(21)]
    r = 0.02  # km: the roundabout's radius
    ring = [pt(10 + r * math.cos(2 * math.pi * i / 12), r * math.sin(2 * math.pi * i / 12) / 111.32) for i in range(12)]
    way(1, line(0, 10 - r), highway="primary", ref="1")
    way(2, ring + ring[:1], highway="primary", junction="roundabout")
    way(3, line(10 + r, 12), highway="primary", ref="1")
    way(4, line(0, 5, 0.03), highway="trunk", ref="6", oneway="yes")             # eastbound
    way(5, line(5, 0, 0.0302), highway="trunk", ref="6", oneway="yes")           # westbound, 22 m north
    way(6, line(0, 5, 0.06), highway="motorway", ref="A1", oneway="yes")          # motorway
    way(7, line(0, 3, 0.09), highway="motorway", ref="8", oneway="no")            # class I road 8, as motorway
    way(11, line(3, 4, 0.09), highway="motorway", ref="8", oneway="no")           # ... in a settlement: no segment
    way(8, line(0, 2, 0.12), highway="primary", name="Околовръстен път")          # ring road 18, no ref
    way(9, line(0, 3, 0.15), highway="secondary", ref="99")                      # class II, segments
    way(10, line(0, 3, 0.18), highway="secondary", ref="20")                     # class II, none
    # Road 2, two carriageways 20 m apart from km -0.6 to 5.6 joined by
    # roundabouts at the ends; its segments of both directions have the
    # eastbound carriageway's ends.
    east, west = line(-0.6, 5.6, 0.21), line(5.6, -0.6, 0.21018)
    way(20, east, highway="trunk", ref="2", oneway="yes")
    way(21, west, highway="trunk", ref="2", oneway="yes")
    way(22, [east[-1], west[0]], highway="trunk", junction="roundabout")
    way(23, [west[-1], east[0]], highway="trunk", junction="roundabout")
    pts = "".join(f'<node id="{i}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"/>' for (lon, lat), i in nodes.items())
    open(path, "w").write('<?xml version="1.0"?><osm version="0.6">' + pts + "".join(ways) + "</osm>")


def seg(cls, road, x0, x1, dy=0.0):
    (lon1, lat1), (lon2, lat2) = pt(x0, dy), pt(x1, dy)
    return [cls, road, "1", round(lat1, 6), round(lon1, 6), round(lat2, 6), round(lon2, 6), round(abs(x1 - x0) * 1000)]


def main():
    d = tempfile.mkdtemp()
    src, dst, law = os.path.join(d, "bg.osm"), os.path.join(d, "bg.json.gz"), os.path.join(d, "bg-network.json")
    osm(src)
    rows = [seg("I", "1", 0, 4), seg("I", "1", 4, 0), seg("I", "1", 6, 9.5), seg("I", "1", 9.5, 6),   # the settlement 4-6 left out
            seg("I", "1", 9.5, 11), seg("I", "1", 11, 9.5),                                          # across the roundabout
            seg("I", "6", 0, 5, 0.03), seg("I", "6", 5, 0, 0.0302),                                  # each carriageway
            seg("I", "8", 0, 3, 0.09), seg("I", "8", 3, 0, 0.09),
            seg("II", "18", 0, 2, 0.12), seg("II", "18", 2, 0, 0.12),
            seg("II", "99", 0, 3, 0.15), seg("II", "99", 3, 0, 0.15),
            seg("I", "2", 0, 5, 0.21), seg("I", "2", 5, 0, 0.21)]                                   # each on its carriageway, no U-turn
    json.dump({"source": "test: x", "roads": {"mw": ["A-1"], "I": ["1", "2", "6", "8"], "II": ["18", "99"]},
               "segments_2022": {"source": "segments: y", "rows": rows}}, open(law, "w"))
    build.RULES["BG"]["segments"] = law
    build.main("BG", src, dst)
    out = json.load(gzip.open(dst))
    km = lambda lines: sum(sum(math.hypot((l[i + 2] - l[i]) / 1e5 / KM, (l[i + 3] - l[i + 1]) / 1e5 * 111.32) for i in range(0, len(l) - 2, 2)) for l in lines)
    nat, mw = km(out["nat"]), km(out["mw"])
    want = 4 + 5 + 10 + 3 + 2 + 3 + 10  # road 1: 0-4, 6-11; road 6's carriageways; 8; 18; 99; road 2's carriageways
    ok = abs(nat - want) < 0.15 and abs(mw - 5) < 0.05 and "toll segments of segments" in out["network"]
    print(f"nat {nat:.2f} km (want {want} and the roundabout's half), mw {mw:.2f} km (want 5: A1, not road 8 nor its stretch in a settlement)")
    for f in (src, dst, law):
        os.remove(f)
    os.rmdir(d)
    if not ok:
        sys.exit("test_bg: FAILED")
    print("test_bg: ok")


if __name__ == "__main__":
    main()
