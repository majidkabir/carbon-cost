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
    # Road 47, 2.2 km south: annex 1's chainage runs past 1000 m in a km
    # (204+2245); the gap 47u204k2245m between two sections is tolled.
    way(40, line(0, 2.767, dy=-0.02), highway="primary", ref="47")    # section 47u203k452m (203+452 - 204+2245)
    way(41, line(2.767, 3.769, dy=-0.02), highway="primary", ref="47")  # 47u204k2245m, missing in OSM's relations
    way(42, line(3.769, 8.872, dy=-0.02), highway="primary", ref="47")  # section 47u205k517m (205+517 - 210+581)
    # Road 38, 2.2 km further south: 38u0k0m ends at 0+3134, 38u1k565m
    # starts at 1+565: the annex doesn't join them (at least the 565 m
    # after km post 1 between them), so the way between isn't tolled.
    way(43, line(0, 3.125, dy=-0.04), highway="primary", ref="38")    # section 38u0k0m
    way(44, line(3.125, 4.0, dy=-0.04), highway="primary", ref="38")  # between: not in the annex
    way(45, line(4.0, 7.802, dy=-0.04), highway="primary", ref="38")  # section 38u1k565m
    # Road 32, 2.2 km further south: 32u9k695m (727 m) missing in OSM's
    # relations, then a 47 m stretch at a junction the annex leaves
    # between it and 32u10k510m: all tolled.
    way(46, line(0, 1.388, dy=-0.06), highway="primary", ref="32")    # section 32u8k277m
    way(47, line(1.388, 2.115, dy=-0.06), highway="primary", ref="32")  # 32u9k695m, missing in OSM's relations
    way(48, line(2.115, 2.162, dy=-0.06, steps=1), highway="primary", ref="32")  # the 47 m at the junction
    way(49, line(2.162, 4.271, dy=-0.06), highway="primary", ref="32")  # section 32u10k510m
    # Road 12: a 0.8 km hole inside 12u8k756m's relation, tolled at its
    # share (0.088).
    way(50, line(0, 1.0, dy=-0.08), highway="primary", ref="12")      # 12u8k756m
    way(51, line(1.0, 1.8, dy=-0.08), highway="primary", ref="12")    # its hole
    way(52, line(1.8, 2.788, dy=-0.08), highway="primary", ref="12")  # 12u8k756m
    # Road 14: 14u3k670m (0.022) then 14u6k105m (0.428), whose relation
    # lacks its first km: that km (drawn from 14u3k670m on) at 0.428.
    way(53, line(0, 2.435, dy=-0.10), highway="primary", ref="14")    # 14u3k670m
    way(54, line(2.435, 3.435, dy=-0.10), highway="primary", ref="14")  # 14u6k105m's first km, missing
    way(55, line(3.435, 4.772, dy=-0.10), highway="primary", ref="14")  # 14u6k105m
    # Road 57: 57u28k530m, a 90 m hole, 57u33k950m (missing in OSM's
    # relations, 0.593), an 83 m hole, 57u34k623m: all tolled.
    way(56, line(0, 2, dy=-0.12), highway="primary", ref="57")        # 57u28k530m
    way(57, line(2, 2.846, dy=-0.12), highway="primary", ref="57")    # 90 m + 57u33k950m + 83 m
    way(58, line(2.846, 4.846, dy=-0.12), highway="primary", ref="57")  # 57u34k623m
    secs = (("12u8k756m", [50, 52]), ("14u3k670m", [53]), ("14u6k105m", [55]), ("57u28k530m", [56]), ("57u34k623m", [58]), ("32u8k277m", [46]), ("32u10k510m", [49]), ("38u0k0m", [43]), ("38u1k565m", [45]), ("47u203k452m", [40]), ("47u205k517m", [42]), ("3u22k810m", [1]), ("3u25k636m", [4]), ("3u17k534m", [7]), ("M0u0k0m", [11]),
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
    # The notes name the annex's sections (provenance road_classes).
    named = "25/2013. (V. 31.) NFM" in out.get("network", "")
    # A gap's km take the share of the annex's sections there: road 21's
    # 21u7k310m (0.134) and 21u10k715m to the roundabout and on, 21u11k1015m
    # (0.788), not the share of the section at one end.
    at = lambda x0, x1, dy=0.02: {round(f, 3) for l, f in zip(out["nat"], out["natf"])
                                  if abs(l[1] / 1e5 - LAT - dy) < 0.0002 and x0 < ((l[0] + l[-2]) / 2e5 - LON0) / KM < x1}
    print("shares: road 21's gaps", at(21, 24), at(26, 29), "road 12's hole", at(1.1, 1.7, -0.08), "road 14's", at(2.5, 3.4, -0.10), "road 57's", at(2.1, 2.8, -0.12))
    named = (named and at(21, 24) == {0.134} and at(26, 27.4) <= {0.788} and at(27.6, 29) <= {0.788}
             and at(1.1, 1.7, -0.08) == {0.088} and at(2.5, 3.4, -0.10) == {0.428} and at(2.1, 2.8, -0.12) == {0.593})
    return km(out["nat"]), km(out["mw"]), len(out["natf"]) == len(out["nat"]) and named


def main():
    sections = 12 + 6 + 6 + 2 + 2.96 + 8.872 + 6.927 + 4.271 + 2.788 + 4.772 + 4.846  # roads 12, 14, 57; road 32: 1.388 + 0.727 + 0.047 + 2.109; road 47: 2.767 + 1.002 + 5.103; road 38: 3.125 + 3.802; road 3: 3 + 3 + 1, the other carriageway 3, the gap 2; road 21: 2 x 1 + 2 x 2 + 2, its dual gap 2 x 3, the gap across the roundabout 2.96
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
