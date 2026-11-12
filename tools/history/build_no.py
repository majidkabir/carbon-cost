"""Builds the Norwegian toll stations from 1 January 2024 to the day
before the current table (rates/data/no-<date>.json) from every version of
NVDB's Bomstasjon objects (type 45), as fetch.py saved them with
alle_versjoner=true (no-nvdb-45-hist*.json and the road link sequences
no-nvdb-45-hist-links-*.json).

Usage: python3 build_no.py fetched/ out-dir -> out-dir/no-2024-01-01.json

Each version becomes a toll point as tools/tables/no.py makes it, in force
from its start date (metadata.startdato) to the day before its end date
(metadata.sluttdato), cut to the table's dates."""
import datetime, glob, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tables"))
import no  # noqa: E402

FROM = "2024-01-01"


def main(fetched, out, data="rates/data"):
    cur = max(json.load(open(f))["valid_from"] for f in glob.glob(os.path.join(data, "no-*.json"))
              if json.load(open(f))["valid_from"] > FROM)
    to = (datetime.date.fromisoformat(cur) - datetime.timedelta(days=1)).isoformat()
    objs, seqs = [], {}
    for f in sorted(glob.glob(os.path.join(fetched, "no-nvdb-45-hist*.json"))):
        d = json.load(open(f))
        if "-links-" in f:
            for s in d.get("objekter", d if isinstance(d, list) else []):
                seqs[s["veglenkesekvensid"]] = s
        else:
            objs += d.get("objekter", [])
    points, left_out, n = [], set(), 0
    for o in sorted(objs, key=lambda o: (o["id"], o["metadata"]["startdato"])):
        start = o["metadata"]["startdato"][:10]
        end = o["metadata"].get("sluttdato")
        last = (datetime.date.fromisoformat(end[:10]) - datetime.timedelta(days=1)).isoformat() if end else None
        if start > to or (last and last < FROM):
            continue
        n += 1
        tp, why = no.point(o, seqs, closed=True)
        if tp is None:
            left_out.add(why)
            continue
        if start > FROM:
            tp["valid_from"] = start
        if last and last < to:
            tp["valid_to"] = last
        points.append(tp)
    # Versions that changed nothing priced here are merged.
    merged = []
    for tp in points:
        p = merged[-1] if merged else None
        same = p and {k: v for k, v in p.items() if k not in ("valid_from", "valid_to")} == {k: v for k, v in tp.items() if k not in ("valid_from", "valid_to")}
        if same and p.get("valid_to") and tp.get("valid_from") and \
                (datetime.date.fromisoformat(p["valid_to"]) + datetime.timedelta(days=1)).isoformat() == tp["valid_from"]:
            p.pop("valid_to")
            if tp.get("valid_to"):
                p["valid_to"] = tp["valid_to"]
            continue
        merged.append(tp)
    tb = {
        "country": "NO", "currency": "NOK", "valid_from": FROM, "valid_to": to,
        "name": "Norwegian road tolls (bompenger, AutoPASS toll stations)",
        "law": "Veglova § 27 and the toll projects' Storting decisions; prices per passage for large vehicles (takstgruppe 2, over 3,500 kg) as registered for each AutoPASS toll station in NVDB, Statens vegvesen's national road database (object type 45 Bomstasjon), every version of each station with the dates it was registered for, with the charged direction and the hour rule (timesregel: after a paid passage the project's other stations are free for the time given). A station's version is the one in force on the trip's date. Rush-hour prices are higher at some stations: the off-peak price is used. Tolls carry no VAT.",
        "sources": [{"title": "NVDB API: Bomstasjon (Statens vegvesen), all versions", "url": "https://nvdbapiles.atlas.vegvesen.no/vegobjekter/api/v4/vegobjekter/45?alle_versjoner=true"}],
        "vehicles": "Vehicles over 3,500 kg (takstgruppe 2)",
        "min_kg": 3501,
        "tolled_roads": "AutoPASS toll stations, each charged when the route passes it in a charged direction while the version is in force.",
        "toll_points": merged,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"no-{FROM}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, n, "versions,", len(merged), "toll points; left out:", "; ".join(sorted(left_out)))


if __name__ == "__main__":
    main(*sys.argv[1:])
