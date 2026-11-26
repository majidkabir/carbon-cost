"""Tests build.py's Czech rule on a small OSM file: a way counts only
where the toll operator's map, read at its points (cz_myto.py), draws
its class's layer; a class I road the law doesn't list isn't tolled; a
short tolled blip (a crossing) is left out; a way the capture doesn't
know is tolled when both its ends meet tolled ways of its class.

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

    def way(wid, x0, x1, dy=0.0, **tags):
        steps = max(1, round(abs(x1 - x0) * 2))
        ids = [node(x0 + (x1 - x0) * i / steps, dy) for i in range(steps + 1)]
        nds = "".join(f'<nd ref="{i}"/>' for i in ids)
        tg = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        ways.append(f'<way id="{wid}" version="1">{nds}{tg}</way>')

    way(1, 0, 10, highway="primary", ref="38")                       # tolled but km 4-6 (a town)
    way(2, 0, 5, dy=0.02, highway="primary", ref="2")                # not in the law
    way(3, 0, 5, dy=0.05, highway="motorway", ref="D1", oneway="yes")
    way(4, 5, 0, dy=0.0502, highway="motorway", ref="D1", oneway="yes")
    way(5, 0, 3, dy=0.08, highway="motorway", ref="D0")              # not tolled on the map
    way(6, 11, 13, highway="primary", ref="38")                      # tolled
    way(8, 0, 5, dy=-0.03, highway="primary", ref="38")              # a blip at km 2.5 only
    if new:
        way(7, 10, 11, highway="primary", ref="38")                  # new: between tolled ends
        way(9, 13, 14, highway="primary", ref="38")                  # new: one end loose
    pts = "".join(f'<node id="{i}" version="1" lat="{LAT + dy:.7f}" lon="{LON0 + x * KM:.7f}"/>' for (x, dy), i in nodes.items())
    open(path, "w").write('<?xml version="1.0"?><osm version="0.6">' + pts + "".join(ways) + "</osm>")


def tolled(wid, x):
    """The map: km x of way wid tolled."""
    return {1: not 4 <= x <= 6, 3: True, 4: True, 6: True, 8: 2.4 <= x <= 2.6}.get(wid, False)


def main():
    d = tempfile.mkdtemp()
    src, dst = os.path.join(d, "cz.osm"), os.path.join(d, "cz.json.gz")
    build.CZ_LAW = os.path.join(d, "law.json")
    json.dump({"source": "test: x", "sections": [{"class": "nat", "ref": "38", "km": 11.0, "text": "I/38"},
                                                  {"class": "mw", "ref": "D1", "km": 5.0, "text": "D1"}]}, open(build.CZ_LAW, "w"))
    cz_myto.SAMPLES, cz_myto.CAPTURE = os.path.join(d, "samples.json.gz"), os.path.join(d, "capture.json")
    osm(src, False)
    build.main("CZ", src, dst)
    os.replace(os.path.join(d, "cz-samples.json.gz"), cz_myto.SAMPLES)
    doc = json.load(gzip.open(cz_myto.SAMPLES))
    sampled = {w[0] for w in doc["ways"]}
    bits = []
    for wid, c, n, xy in doc["ways"]:
        x = 0
        for i in range(n):
            x += xy[2 * i]
            bits.append(tolled(wid, (x / 1e5 - LON0) / KM))
    runs, cur, n = [], False, 0
    for b in bits:
        if b == cur:
            n += 1
        else:
            runs.append(n)
            cur, n = b, 1
    runs.append(n)
    raw = open(cz_myto.SAMPLES, "rb").read()
    json.dump({"url": "test", "date": "2026-11-27", "samples_sha256": hashlib.sha256(raw).hexdigest(), "points": len(bits),
               "runs": ",".join(map(str, runs))}, open(cz_myto.CAPTURE, "w"))
    osm(src, True)
    build.main("CZ", src, dst)
    out = json.load(gzip.open(dst))
    km = lambda lines: sum(sum(((l[i + 2] - l[i]) ** 2 + (l[i + 3] - l[i + 1]) ** 2) ** 0.5 for i in range(0, len(l) - 2, 2)) for l in lines) / 1e5 / KM
    nat, mw = km(out["nat"]), km(out["mw"])
    ok = sampled == {1, 3, 4, 5, 6, 8} and abs(nat - 11) < 0.15 and abs(mw - 10) < 0.15 and out["network"] == "test; tolled stretches as the toll operator's map draws them (test, read 2026-11-27)"
    print(f"sampled {sorted(sampled)} (want 1, 3, 4, 5, 6, 8: not road 2), nat {nat:.2f} km (want 11: 10 - 2 + 2 + 1, not the blip nor the loose way), mw {mw:.2f} km (want 10: D1's two carriageways, not D0)")
    print(out["network"])
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    os.rmdir(d)
    if not ok:
        sys.exit("test_cz: FAILED")
    print("test_cz: ok")


if __name__ == "__main__":
    main()
