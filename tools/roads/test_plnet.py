"""Tests plnet on a small synthetic OpenStreetMap file: python3 test_plnet.py"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plnet

nodes, ways, nid, wid = [], [], [0], [0]


def node(lon, lat, **tags):
    nid[0] += 1
    nodes.append((nid[0], lon, lat, tags))
    return nid[0]


def way(ids, **tags):
    wid[0] += 1
    ways.append((wid[0], ids, tags))


# S7, a dual carriageway along 52.0 N from 20.00 to 20.10 E, 33 m apart,
# junctions Alfa (20.02) and Beta (20.08) on both carriageways.
for lat in (52.0, 52.0003):
    ids = []
    for i in range(11):
        lon = 20.0 + i * 0.01
        name = {2: "Alfa", 8: "Beta"}.get(i)
        ids.append(node(lon, lat, highway="motorway_junction", name=name) if name else node(lon, lat))
    way(ids, highway="motorway", ref="S7", oneway="yes")
# National road 92 along 52.1 N from 20.00 to 20.20, through the city
# Miasto (20.05-20.10), crossing county road 1234X at 20.15 by Wieś.
ids, cross = [], None
for i in range(21):
    ids.append(node(20.0 + i * 0.01, 52.1))
    if i == 15:
        cross = ids[-1]
way(ids, highway="primary", ref="92")
way([node(20.15, 52.09), cross, node(20.15, 52.11)], highway="secondary", ref="1234X")
node(20.151, 52.105, place="village", name="Wieś")
b = [node(20.05, 52.05), node(20.105, 52.05), node(20.105, 52.15), node(20.05, 52.15)]
way(b + [b[0]], boundary="administrative", admin_level="6", name="Miasto")
# A4 from a dead end at the border by Granica (19.00) east to Gamma.
way([node(19.0 + i * 0.01, 51.0, **({"highway": "motorway_junction", "name": "Gamma"} if i == 5 else {})) for i in range(8)], highway="motorway", ref="A4")
node(19.0, 51.01, place="village", name="Granica")


def write(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n')
        for i, lon, lat, tags in nodes:
            tg = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
            f.write(f'<node id="{i}" version="1" lat="{lat}" lon="{lon}">{tg}</node>\n')
        for i, ids, tags in ways:
            nd = "".join(f'<nd ref="{n}"/>' for n in ids)
            tg = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
            f.write(f'<way id="{i}" version="1">{nd}{tg}</way>\n')
        f.write("</osm>\n")


def main():
    sections = [
        {"class": "mw", "ref": "S7", "from": {"junction": "Alfa"}, "to": {"junction": "Beta"}, "text": "S7 węzeł Alfa – węzeł Beta"},
        {"class": "nat", "ref": "92", "from": {"city": "Miasto"}, "to": {"place": "Wieś", "street": None, "crosses": ["1234X"]}, "text": "92 granica m. Miasto – Wieś"},
        {"class": "mw", "ref": "A4", "from": {"border": "Granica"}, "to": {"junction": "Gamma"}, "text": "A4 Granica – węzeł Gamma"},
        {"class": "mw", "ref": "S7", "from": {"junction": "Alfa"}, "to": {"junction": "Delta"}, "text": "S7 węzeł Alfa – węzeł Delta"},
    ]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.osm")
        write(path)
        lines, report = plnet.build(path, sections)
    got = {text: km for text, km, why in report}
    fails = 0
    for text, want in (("S7 węzeł Alfa – węzeł Beta", 4.13), ("92 granica m. Miasto – Wieś", 2.74), ("A4 Granica – węzeł Gamma", 3.5)):
        if got.get(text) is None or abs(got[text] - want) > 0.1:
            print("FAIL", text, got.get(text), "want", want)
            fails += 1
    if got.get("S7 węzeł Alfa – węzeł Delta") is not None:
        print("FAIL: Delta found")
        fails += 1
    # Both S7 carriageways, 6 nodes each from Alfa to Beta.
    s7 = [l for l in lines["mw"] if abs(l[0][1] - 52.0) < 0.001]
    if sorted(len(l) for l in s7) != [7, 7]:
        print("FAIL S7 lines", [len(l) for l in s7])
        fails += 1
    if len(lines["nat"]) != 1 or abs(lines["nat"][0][0][0] - 20.11) > 1e-6 or abs(lines["nat"][0][-1][0] - 20.15) > 1e-6:
        print("FAIL 92 line", lines["nat"])
        fails += 1
    print("ok" if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
