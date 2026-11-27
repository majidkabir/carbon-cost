"""Tests build.py's Czech rule on a small OSM file: a way counts only
where the toll operator's map, read at its points (cz_myto.py), draws a
layer, in that layer's class (a class II road in OpenStreetMap the map
tolls as class I, a motorway it tolls as class I); a short tolled blip
(a crossing) is left out, and so is a road beside a motorway the map's
line is the motorway's; a way takes the map's reading at the points on it,
its own or (OSM split, merged or moved it) others' running along it, not
a crossing road's, and where none is, the layer of the slots on both
sides (for a few) or none; a way added since, mostly unread and read only
at its ends, is tolled when the ways of its ref joined to it, and
ref-less ones between, meet ways of that ref tolled at every end (their
ends or inside them).

Usage: python3 test_cz.py
"""
import gzip, hashlib, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402
import cz_myto  # noqa: E402

# Along latitude 49.5 from 15.0° E (1 km is about 0.01384° of longitude).
KM = 1 / (111.32 * 0.6494)
LAT, LON0 = 49.5, 15.0


def osm(path, new):
    nodes, ways = {}, []

    def node(x, dy):
        key = (round(x, 6), dy)
        if key not in nodes:
            nodes[key] = len(nodes) + 1
        return nodes[key]

    def way(wid, x0, x1=None, dy=0.0, **tags):
        if x1 is None:  # a list of (km, dy) points
            ids = [node(x, y) for x, y in x0]
        else:
            steps = max(1, round(abs(x1 - x0) * 2))
            ids = [node(x0 + (x1 - x0) * i / steps, dy) for i in range(steps + 1)]
        nds = "".join(f'<nd ref="{i}"/>' for i in ids)
        tg = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        ways.append(f'<way id="{wid}" version="1">{nds}{tg}</way>')

    if new:
        # OSM split way 1 at the town's end: the old id keeps km 6-10.
        way(13, 0, 6, highway="primary", ref="38")
        way(1, 6, 10, highway="primary", ref="38")
    else:
        way(1, 0, 10, highway="primary", ref="38")                   # tolled but km 4-6 (a town)
    way(2, 0, 5, dy=0.02, highway="primary", ref="2")                # not in the law
    way(3, 0, 5, dy=0.05, highway="motorway", ref="D1", oneway="yes")
    way(4, 5, 0, dy=0.0502, highway="motorway", ref="D1", oneway="yes")
    way(5, 0, 3, dy=0.08, highway="motorway", ref="D0")              # not tolled on the map
    if new:
        way(6, 11, 13.8, highway="primary", ref="38")                # OSM merged way 16 into it
    else:
        way(6, 11, 13, highway="primary", ref="38")                  # tolled
        way(16, 13, 13.8, highway="primary", ref="38")               # tolled
    way(8, 0, 5, dy=-0.03, highway="primary", ref="38")              # a blip at km 2.5 only
    way(10, 0, 3, dy=-0.06, highway="secondary", ref="434")          # class I on the map
    way(11, 0, 2, dy=-0.09, highway="motorway", ref="55")            # class I on the map
    way(12, 0, 4, dy=0.0503, highway="secondary", ref="607")         # beside D1, 33 m off: the map's line is D1's
    if new:
        way(7, 10, 10.5, highway="primary", ref="38")                # new: two ways between tolled ends
        way(14, 10.5, 11, highway="motorway", ref="38", oneway="no")  # (a class I road tagged motorway)
        way(9, 13.8, 14.8, highway="primary", ref="38")              # new: one end loose
        way(17, [(10, 0), (10, 0.003), (11, 0.003), (11, 0)], highway="secondary", ref="999")  # new: another road between tolled ends
        way(18, [(12.05, -0.0007), (12.05, 0.0007)], highway="primary", ref="2")             # new: crossing way 6 at one of its points
    # Stretches of road 38 OSM changed after the map was read, each at its
    # own latitude (BANDS: the km tolled there, at the end).
    D = -0.12
    if new:
        way(30, 0, 2.12, D, highway="primary", ref="38")              # merged the one-point way 31
    else:
        way(30, 0, 2, D, highway="primary", ref="38")
        way(31, 2, 2.12, D, highway="primary", ref="38")
    way(32, 2.12, 4, D, highway="primary", ref="38")
    D = -0.15
    way(35 if new else 33, 0, 3, D, highway="primary", ref="38")       # a new id, a secondary 11 m off
    way(34, 0, 3, D + 0.0001, highway="secondary", ref="333")
    D = -0.18
    way(36, 0, 5, D, highway="primary", ref="38")
    way(37, 7, 12, D, highway="primary", ref="38")
    if new:                                                           # new: 38 across a ref-less roundabout piece
        way(41, 5, 5.95, D, highway="primary", ref="38")
        way(42, 5.95, 6.05, D, highway="primary", junction="roundabout")
        way(43, 6.05, 7, D, highway="primary", ref="38")
    D = -0.21
    way(44, 0, 2, D, highway="primary", ref="38")
    way(45, 3, 5, D, highway="primary", ref="35")
    if new:
        way(46, 2, 3, D, highway="primary")                           # new: ref-less, from 38 to 35
    D = -0.24
    way(47, 0, 2, D, highway="primary", ref="38")
    way(48, 3, 5, D, highway="primary", ref="38")
    if new:                                                           # new: a dual carriageway between them
        way(49, 2, 3, D, highway="primary", ref="38", oneway="yes")
        way(50, [(3, D), (2.5, D + 0.0002), (2, D)], highway="primary", ref="38", oneway="yes")
    D = -0.30
    way(52, 0, 5, D, highway="primary", ref="38")
    way(53, 7, 12, D, highway="primary", ref="38")
    if new:                                                           # new: 38 and a ref-less road crossing it
        way(54, 5, 7, D, highway="primary", ref="38")
        way(55, [(6, D - 0.006), (6, D), (6, D + 0.006)], highway="primary")
    D = -0.33
    way(56, 0, 12, D, highway="primary", ref="38")
    if new:                                                           # new: a bypass from inside way 56 to inside it
        way(57, BYPASS[D], highway="primary", ref="38")
    D = -0.36
    way(58, 0, 4, D, highway="primary", ref="38")
    way(59, 4, 6, D, highway="primary", ref="38")                     # the town passage, untolled
    way(60, 6, 10, D, highway="primary", ref="38")
    if new:                                                           # new: a bypass first 11 m beside the town passage
        way(61, BYPASS[D], highway="primary", ref="38")
    D = -0.39
    way(62, 0, 5, D, highway="primary", ref="38")
    way(63, 7, 12, D, highway="primary", ref="38")
    if new:                                                           # new: 38 through a roundabout OSM split in two
        A, B, TOP, LOW = (5.9, D), (6.1, D), (6.0, D + 0.0009), (6.0, D - 0.0009)
        way(64, 5, 5.9, D, highway="primary", ref="38")
        way(65, [A, TOP], highway="primary", junction="roundabout", oneway="yes")
        way(66, [TOP, B, LOW, A], highway="primary", junction="roundabout", oneway="yes")
        way(67, 6.1, 7, D, highway="primary", ref="38")
    D = -0.42
    way(68, 0, 10, D, highway="primary", ref="38")
    if new:                                                           # new: a ref-less street off way 68 and back
        way(69, [(3, D), (3.5, D + 0.003), (4.5, D + 0.003), (5, D)], highway="primary")
    D = -0.45
    way(70, 0, 4, D, highway="primary", ref="38")
    way(72, 6, 10, D, highway="primary", ref="38")
    if new:                                                           # the town passage, moved 40 m off at km 4.2-5.8
        way(71, [(4, D), (4.2, D), (4.2, D + 0.00036), (5.8, D + 0.00036), (5.8, D), (6, D)], highway="primary", ref="38")
    else:
        way(71, 4, 6, D, highway="primary", ref="38")
    D = -0.48
    if new:                                                           # the town passage at km 4-6, moved 40 m off at km 4.2-5.8 (the same id)
        way(73, [(0, D), (4, D), (4.2, D), (4.2, D + 0.00036), (5.8, D + 0.00036), (5.8, D), (6, D), (10, D)], highway="primary", ref="38")
    else:
        way(73, 0, 10, D, highway="primary", ref="38")
    D = -0.51
    if new:                                                           # way 80 split at km 0.475: the new 83 a few slots long, one unread
        way(80, 0, 0.475, D, highway="primary", ref="38")
        way(83, 0.475, 1.027, D, highway="primary", ref="38")
    else:
        way(80, 0, 1.027, D, highway="primary", ref="38")
    way(81, 1.027, 3, D, highway="primary", ref="38")                 # the town passage, untolled
    way(82, 3, 6, D, highway="primary", ref="38")
    D = -0.54
    way(84, 0, 5, D, highway="primary", ref="38")
    way(85, 5.2, 10, D, highway="primary", ref="38")
    if new:                                                           # the link between them now a roundabout (ref-less, closed)
        way(87, RING, highway="primary", junction="roundabout", oneway="yes")
    else:
        way(86, 5, 5.2, D, highway="primary", ref="38")
    D = -0.27
    if new:                                                           # moved 40 m off at km 1.2-1.6
        way(51, [(0, D), (0.5, D), (1.2, D), (1.2, D + 0.00036), (1.6, D + 0.00036), (1.6, D), (3, D)], highway="primary", ref="38")
    else:
        way(51, 0, 3, D, highway="primary", ref="38")
    pts = "".join(f'<node id="{i}" version="1" lat="{LAT + dy:.7f}" lon="{LON0 + x * KM:.7f}"/>' for (x, dy), i in nodes.items())
    open(path, "w").write('<?xml version="1.0"?><osm version="0.6">' + pts + "".join(ways) + "</osm>")


RING = [(5, -0.54), (5.1, -0.5391), (5.2, -0.54), (5.1, -0.5409), (5, -0.54)]
BYPASS = {-0.33: [(4.5, -0.33), (4.6, -0.3297), (7.4, -0.3297), (7.5, -0.33)],
          -0.36: [(4, -0.36), (4.25, -0.3599), (4.5, -0.358), (5.5, -0.358), (6, -0.36)]}


def km_of(pts):
    """The km of (km, dy) points as the test measures lines."""
    return sum(((x2 - x1) ** 2 + ((y2 - y1) / KM) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(pts, pts[1:]))


def drawn(wid, x):
    """The map: the layer drawn at km x of way wid."""
    if wid == 1:
        return None if 4 <= x <= 6 else "nat"
    if wid == 73:
        return None if 4 <= x <= 6 else "nat"
    if wid == 8:
        return "nat" if 2.4 <= x <= 2.6 else None
    return {3: "mw", 4: "mw", 6: "nat", 16: "nat", 10: "nat", 11: "nat", 12: "mw",
            30: "nat", 31: "nat", 32: "nat", 33: "nat", 36: "nat", 37: "nat", 44: "nat", 45: "nat", 47: "nat", 48: "nat", 51: "nat",
            52: "nat", 53: "nat", 56: "nat", 58: "nat", 60: "nat", 62: "nat", 63: "nat", 68: "nat", 70: "nat", 72: "nat", 80: "nat", 82: "nat", 84: "nat", 85: "nat", 86: "nat"}.get(wid)


# The stretches' latitudes (dy) and the class I km tolled there: 30-32
# whole; 35 (not the secondary); 36, 37 and the new ways between; 44 and 45
# (not the ref-less way between); 47, 48 and both carriageways between;
# 51 with its moved bit; 52, 53 and the new way between, not the ref-less
# road crossing it; 56 and the bypass joining it inside; 58, 60 and the
# bypass round the town, not the passage; 62, 63 and the new ways and
# split roundabout between; 68, not the ref-less street off it and back;
# 70 and 72, not the passage OSM moved; 73 but the passage OSM moved;
# 80, 83 and 82, not the passage; 84, 85 and the roundabout between them.
BANDS = {-0.12: 4.0, -0.15: 3.0, -0.18: 12.0, -0.21: 4.0, -0.24: 6.0, -0.27: 3.08,
         -0.30: 12.0, -0.33: 12 + km_of(BYPASS[-0.33]), -0.36: 8 + km_of(BYPASS[-0.36]),
         -0.39: 10 + 0.9 + 0.9 + km_of([(5.9, -0.39), (6.0, -0.3891), (6.1, -0.39), (6.0, -0.3909), (5.9, -0.39)]),
         -0.42: 10.0, -0.45: 8.0, -0.48: 7.9, -0.51: 4.027, -0.54: 9.8 + km_of(RING)}  # -0.48: 8 but a slot at the passage's end


def main():
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, "cz.osm"), os.path.join(d, "cz.json.gz")
    build.CZ_LAW = os.path.join(d, "law.json")
    json.dump({"source": "test: x", "sections": [{"class": "nat", "ref": "38", "km": 135.6, "text": "I/38"},
                                                  {"class": "mw", "ref": "D1", "km": 5.0, "text": "D1"}]}, open(build.CZ_LAW, "w"))
    cz_myto.SAMPLES, cz_myto.CAPTURE = os.path.join(d, "samples.json.gz"), os.path.join(d, "capture.json")
    osm(src, False)
    build.main("CZ", src, dst)
    os.replace(os.path.join(d, "cz-samples.json.gz"), cz_myto.SAMPLES)
    doc = json.load(gzip.open(cz_myto.SAMPLES))
    sampled = {w[0] for w in doc["ways"]}
    tolled, other = [], []
    for wid, c, n, xy in doc["ways"]:
        x = 0
        for i in range(n):
            x += xy[2 * i]
            layer = drawn(wid, (x / 1e5 - LON0) / KM)
            tolled.append(layer is not None)
            other.append(layer is not None and layer != c)

    def runs(bits):
        out, cur, n = [], False, 0
        for b in bits:
            if b == cur:
                n += 1
            else:
                out.append(n)
                cur, n = b, 1
        return ",".join(map(str, out + [n]))
    raw = open(cz_myto.SAMPLES, "rb").read()
    json.dump({"url": "test", "date": "2026-11-27", "samples_sha256": hashlib.sha256(raw).hexdigest(), "points": len(tolled),
               "runs": runs(tolled), "other": runs(other), "unmatched": [["nat", 15.1, 49.4, 1200]]}, open(cz_myto.CAPTURE, "w"))
    osm(src, True)
    build.CHANGED_KM = 40  # the test changes more than a real extract may
    build.main("CZ", src, dst)
    out = json.load(gzip.open(dst))
    km = lambda lines: sum(sum(((l[i + 2] - l[i]) ** 2 + (l[i + 3] - l[i + 1]) ** 2) ** 0.5 for i in range(0, len(l) - 2, 2)) for l in lines) / 1e5 / KM
    band = lambda dy: [l for l in out["nat"] if abs(l[1] / 1e5 - (LAT + dy)) < 0.005]
    got = {dy: km(band(dy)) for dy in BANDS}
    nat, mw = km(out["nat"]) - sum(got.values()), km(out["mw"])
    bands_ok = all(abs(got[dy] - want) < 0.1 for dy, want in BANDS.items())
    for dy, want in BANDS.items():
        print(f"stretch at {dy}: {got[dy]:.2f} km tolled, want {want}")
    ok = bands_ok and sampled == {1, 2, 3, 4, 5, 6, 8, 10, 11, 12, 16, 30, 31, 32, 33, 34, 36, 37, 44, 45, 47, 48, 51, 52, 53, 56, 58, 59, 60, 62, 63, 68, 70, 71, 72, 73, 80, 81, 82, 84, 85, 86} and abs(nat - 16.8) < 0.15 and abs(mw - 10) < 0.15 and out["network"] == "test; tolled stretches as the toll operator's map draws them (test, read 2026-11-27)"
    print(f"sampled {sorted(sampled)} (want all but the new 7 and 9), nat {nat:.2f} km (want 16.8: 10 - 2 + 2.8 + 1 + 3 + 2, not the blip, the loose way, the other road nor the crossing one), mw {mw:.2f} km (want 10: D1's two carriageways, not D0 nor the road beside D1)")
    print(out["network"])
    # Too much changed since the reading: the build asks for a new one.
    build.CHANGED_KM, asked = 10, ""
    os.remove(os.path.join(d, "cz-samples.json.gz"))
    try:
        build.main("CZ", src, dst)
    except SystemExit as e:
        asked = str(e)
    build.CHANGED_KM = 25
    print("with 10 km allowed:", asked)
    ok = ok and os.path.exists(os.path.join(d, "cz-samples.json.gz"))  # written before it stops
    ok = ok and "take a new reading" in asked
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    os.rmdir(d)
    if not ok:
        sys.exit("test_cz: FAILED")
    print("test_cz: ok")


if __name__ == "__main__":
    main()
