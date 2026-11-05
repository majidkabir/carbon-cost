"""Builds the Norwegian toll station table from the national road
database NVDB (Statens vegvesen), as fetch.py saves it: the toll stations
(object type 45, Bomstasjon: no-nvdb-45*.json) and the road link
sequences they are placed on (no-nvdb-45-links-*.json).

Usage: python3 no.py fetched/ out-dir -> out-dir/no-<date>.json

Each AutoPASS toll station becomes a toll point with:
- its position (geometry, WGS 84; NVDB writes "POINT Z (lat lon h)");
- "Takst stor bil", the price per passage for large vehicles (over
  3,500 kg), and "Rushtidstakst stor bil" where the price is higher in
  rush hours;
- the charged direction ("Innkrevningsretning"): "Begge retninger" or no
  value: both ways; "Med metrering" or "Mot metrering": along or against
  the road link sequence's metering direction, turned into a compass
  heading from the link's geometry (which runs in the metering
  direction) at the station's relative position;
- the hour rule ("Timesregel"): "Første passering gjelder" with its
  passage group and duration: after a paid passage, the group's other
  stations are free for that long.
Stations without a large-vehicle price, ferry collection points and
stations on local or private roads are left out (listed when built). The
table is valid from the latest version date of the stations
(metadata.startdato).
"""
import glob, json, math, os, re, sys


def props(o):
    return {p["navn"]: p.get("verdi") for p in o.get("egenskaper", [])}


def links(fetched):
    out = {}
    for f in sorted(glob.glob(os.path.join(fetched, "no-nvdb-45-links-*.json"))):
        d = json.load(open(f))
        for s in d.get("objekter", d if isinstance(d, list) else []):
            out[s["veglenkesekvensid"]] = s
    return out


def coords(wkt):
    return [tuple(map(float, p.split()[:2])) for p in re.search(r"\((.*)\)", wkt).group(1).split(",")]


def heading_at(seq, rel):
    """Compass heading of the metering direction at relative position rel."""
    for v in seq.get("veglenker", []):
        if v.get("sluttdato") or not (v["startposisjon"] <= rel <= v["sluttposisjon"]):
            continue
        pts = coords(v["geometri"]["wkt"])  # (lat, lon), in metering direction
        if len(pts) < 2:
            continue
        f = (rel - v["startposisjon"]) / (v["sluttposisjon"] - v["startposisjon"])
        seg = [math.hypot((b[0] - a[0]) * 111.2, (b[1] - a[1]) * 111.2 * math.cos(math.radians(a[0]))) for a, b in zip(pts, pts[1:])]
        target, cum = f * sum(seg), 0.0
        for (a, b), l in zip(zip(pts, pts[1:]), seg):
            if cum + l >= target and l > 0:
                dy, dx = (b[0] - a[0]) * 111.2, (b[1] - a[1]) * 111.2 * math.cos(math.radians(a[0]))
                return round(math.degrees(math.atan2(dx, dy)) % 360, 1)
            cum += l
    return None


def main(fetched, out):
    objs = []
    for f in sorted(glob.glob(os.path.join(fetched, "no-nvdb-45*.json"))):
        if "-links-" in f:
            continue
        objs += json.load(open(f)).get("objekter", [])
    seqs = links(fetched)
    points, left_out, dates = [], [], []
    for o in sorted(objs, key=lambda o: o["id"]):
        e = props(o)
        name = (e.get("Navn bomstasjon") or "").strip() or f"NVDB {o['id']}"
        kind = e.get("Bomstasjonstype")
        if kind != "AutoPASS bomstasjon":
            left_out.append(f"{name} ({kind})")
            continue
        if e.get("Takst stor bil") is None:
            left_out.append(f"{name} (no large-vehicle price)")
            continue
        lat, lon = coords(o["geometri"]["wkt"])[0]
        tp = {"name": name}
        if e.get("Navn bompengeanlegg"):
            tp["project"] = e["Navn bompengeanlegg"].strip()
        tp.update(lat=round(lat, 6), lon=round(lon, 6))
        way = e.get("Innkrevningsretning")
        if way in ("Med metrering", "Mot metrering"):
            st = next((s for s in o["lokasjon"]["stedfestinger"] if s.get("veglenkesekvensid") in seqs), None)
            h = heading_at(seqs[st["veglenkesekvensid"]], st["relativPosisjon"]) if st else None
            if h is None:
                left_out.append(f"{name} (charged direction not found on its road link)")
                continue
            if way == "Mot metrering":
                h = round((h + 180) % 360, 1)
            tp["heading"] = h
        tp["rate"] = e["Takst stor bil"]
        if (e.get("Rushtidstakst stor bil") or 0) > tp["rate"]:
            tp["peak_rate"] = e["Rushtidstakst stor bil"]
        if e.get("Timesregel") == "Første passering gjelder" and e.get("Timesregel, passeringsgruppe"):
            tp["group"] = e["Timesregel, passeringsgruppe"]
            tp["group_minutes"] = e.get("Timesregel, varighet") or 60
        points.append(tp)
        dates.append(o["metadata"]["startdato"])
    valid_from = max(dates)
    tb = {
        "country": "NO", "currency": "NOK", "valid_from": valid_from,
        "name": "Norwegian road tolls (bompenger, AutoPASS toll stations)",
        "law": "Veglova § 27 and the toll projects' Storting decisions; prices per passage for large vehicles (takstgruppe 2, over 3,500 kg) as registered for each AutoPASS toll station in NVDB, Statens vegvesen's national road database (object type 45 Bomstasjon), with the charged direction and the hour rule (timesregel: after a paid passage the project's other stations are free for the time given). Rush-hour prices are higher at some stations: the off-peak price is used. Tolls carry no VAT.",
        "sources": [{"title": "NVDB API: Bomstasjon (Statens vegvesen)", "url": "https://nvdbapiles.atlas.vegvesen.no/vegobjekter/api/v4/vegobjekter/45"}],
        "vehicles": "Vehicles over 3,500 kg (takstgruppe 2)",
        "min_kg": 3501,
        "tolled_roads": f"{len(points)} AutoPASS toll stations, each charged when the route passes it in a charged direction.",
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"no-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(points), "toll points; left out:", "; ".join(left_out))


if __name__ == "__main__":
    main(*sys.argv[1:])
