"""Builds Italy's 2025 tables: the motorway toll estimate from the
Ministry's 2025 sheets (tools/tables/it.py's sheets(): each concession's
sheet, transcribed in tools/tables/transcribed/it-mit-*.json, and
Autostrade per l'Italia's own for its network), and the Milan ring roads'
barrier tolls of 2025 from Milano Serravalle's tables (their PDFs give
every year from 2022), placed as the current barrier table places
them (fetched/current; the other barriers were priced per km in 2025's
estimate, so the 2025 table has Milan's only).

Usage: python3 build_it.py fetched/ out-dir"""
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import it, it_barriers  # noqa: E402

TRANSCRIBED = os.path.join(HERE, "..", "tables", "transcribed")


def barriers(fetched, out, year):
    cur = sorted(glob.glob(os.path.join(fetched, "current", "it-barriers-*.json")))
    if not cur:
        sys.exit("no current it-barriers table in fetched/current")
    tb = json.load(open(cur[-1], encoding="utf-8"))
    places = {p["name"]: p for p in tb["toll_points"]}
    points, notes = [], []
    for fid, name, *_ in it_barriers.BARRIERS:
        t, _ = it_barriers.tolls(open(os.path.join(fetched, fid + ".txt"), encoding="utf-8").read(), year)
        p = places[name]
        points.append({"name": name, "lat": p["lat"], "lon": p["lon"], "rate": 0,
                       "classes": [{"min_kg": 3501, "min_axles": 5, "rate": t["5"]}, {"min_kg": 3501, "min_axles": 4, "rate": t["4"]},
                                   {"min_kg": 3501, "min_axles": 3, "rate": t["3"]}, {"min_kg": 3501, "rate": t["B"]}]})
        notes.append(f"{name} class 5 EUR {t['5']:.2f}")
    it_barriers.write(out, year, points, notes)


if __name__ == "__main__":
    fetched, out = sys.argv[1:]
    it.sheets(TRANSCRIBED, out, 2025)
    # 2024 waits for the 2024 estimate: the barriers alone would make the
    # area look covered.
    barriers(fetched, out, 2025)
