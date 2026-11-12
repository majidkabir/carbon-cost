"""Builds London's area charges: the Low Emission Zone and the Congestion
Charge (rates.Zone, data/zone-gb-*.json).

Usage: python3 gb_london.py fetched/ out-dir -> out-dir/zone-gb-<zone>-<date>.json

Charges and hours: Transport for London's pages (fetch.py's gb-tfl-*.html,
the Internet Archive's copies as TfL refuses the workflow). Zones:
OpenStreetMap (gb-london-osm.json: the London Low Emission Zone relation;
gb-london-ccz-osm.json: the Congestion Charge zone), each relation's outer
and inner ways joined into rings.
"""
import html, json, math, os, re, sys


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def rings(rel, role):
    """Joins the relation's ways of a role into closed rings ([lon, lat])."""
    ways = [[(round(p["lon"], 6), round(p["lat"], 6)) for p in m["geometry"]] for m in rel["members"]
            if m["type"] == "way" and m.get("role", "outer") == role and m.get("geometry")]
    out = []
    while ways:
        ring = ways.pop(0)
        while ring[0] != ring[-1]:
            for i, w in enumerate(ways):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[::-1][1:]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[::-1][:-1] + ring
                else:
                    continue
                ways.pop(i)
                break
            else:
                sys.exit(f"{rel['tags'].get('name')}: {role} ways don't close into rings")
        out.append([list(p) for p in ring])
    return out


def relation(path, name):
    d = json.load(open(path))
    rels = [e for e in d["elements"] if e["type"] == "relation" and e.get("tags", {}).get("name") == name and e.get("members")]
    if len(rels) != 1:
        sys.exit(f"{name}: {len(rels)} relations with geometry in {os.path.basename(path)}")
    return rels[0], d.get("osm3s", {}).get("timestamp_osm_base", "")[:10]


def write(out, z, slug):
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, f"zone-gb-{slug}-{z['valid_from']}.json")
    json.dump(z, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
    print(p, z["charge"], sum(len(r) for r in z["polygons"]), "points")


def ccz(fetched, out):
    cc_p, gz_p, osm_p = (os.path.join(fetched, f) for f in ("gb-tfl-cc.html", "gb-gazette-cc-2026.html", "gb-london-ccz-osm.json"))
    if not all(os.path.exists(p) for p in (cc_p, gz_p, osm_p)):
        print("Congestion Charge: a source wasn't fetched; not built")
        return
    t, gz = text(cc_p), text(gz_p)
    m = re.search(r"£(\d+) daily charge \(if paid on the day or in advance\).*?drive within the Congestion Charge zone (\d?\d:\d\d)-(\d?\d:\d\d) Monday-Friday and (\d?\d:\d\d)-(\d?\d:\d\d) Sat-Sun and bank holidays\. No charge between Christmas Day and New Year.s Day bank holiday", t)
    g = re.search(r"increase the level of the Congestion Charge from £(\d+) to £(\d+) .{0,80}?from (\d+) January (\d{4})", gz)
    if not m or not g or g.group(2) != m.group(1):
        sys.exit(f"Congestion Charge: TfL's page or the Gazette notice changed ({bool(m)}, {bool(g)})")
    since = f"{g.group(4)}-01-{int(g.group(3)):02d}"
    rel, stamp = relation(osm_p, "London Congestion Charge")
    poly = rings(rel, "outer")
    hh = [m.group(i).zfill(5) for i in range(2, 6)]
    hours = {"weekdays": hh[:2], "weekends": hh[2:]}
    src = [{"title": "Transport for London: Congestion Charge (the Internet Archive's copy)", "url": "https://tfl.gov.uk/modes/driving/congestion-charge"},
           {"title": "The London Gazette: notice of the Congestion Charge changes", "url": "https://www.thegazette.co.uk/notice/4893898"}]
    law = ("Greater London (Central Zone) Congestion Charging Order 2004, as varied: a charge per day for driving in the zone "
           f"{hh[0]}-{hh[1]} Monday to Friday and {hh[2]}-{hh[3]} at weekends and on bank holidays (bank holidays are taken as weekdays here), "
           "none from Christmas Day to New Year's Day (TfL); the charge paid on the day or in advance")
    for vf, vt, charge in (("2024-01-01", prev_day(since), float(g.group(1))), (since, "", float(g.group(2)))):
        z = {"country": "GB", "currency": "GBP", "valid_from": vf, "name": "London Congestion Charge", "law": law + f", GBP {charge:g} ({'before' if vt else 'from'} {since}, the Gazette notice).",
             "sources": src, "min_kg": 0, "charge": charge, **hours, "no_charge": ["12-25", "01-01"], "polygons": poly, "osm_extract": stamp}
        if vt:
            z["valid_to"] = vt
        write(out, z, "congestion-charge")


def prev_day(d):
    import datetime
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()


def main(fetched, out):
    ccz(fetched, out)
    lez_p = os.path.join(fetched, "gb-tfl-lez-charges.html")
    if not os.path.exists(lez_p) or "Euro VI" not in text(lez_p):
        print("London LEZ: TfL's charges page not fetched; not built")
    else:
        t = text(lez_p)
        print("LEZ:", t[t.find("Euro VI") - 400:t.find("Euro VI") + 600])


if __name__ == "__main__":
    main(*sys.argv[1:])
