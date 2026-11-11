"""Builds Ireland's toll plaza tables for past years from TII's pages as
the Internet Archive kept them, read in a browser into
tools/history/browser/ie-<year>.json (each page's name, APPLICABLE TOLLS
heading and goods-vehicle rows, with the archived URL). Each is written
out as the page's cells and built by tools/tables/ie.py with the
OpenStreetMap toll booths the history workflow copies from tables-out
(fetched/osm/ie-osm.geojsonseq), or those in fetched/.

Usage: python3 build_ie.py fetched/ out-dir"""
import glob, html, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import ie  # noqa: E402


def main(fetched, out):
    osm = next((d for d in (os.path.join(fetched, "osm"), fetched) if os.path.exists(os.path.join(d, "ie-osm.geojsonseq"))), None)
    if osm is None:
        sys.exit("no ie-osm.geojsonseq")
    for f in sorted(glob.glob(os.path.join(HERE, "browser", "ie-*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        tmp = tempfile.mkdtemp()
        for name in ("ie-osm.geojsonseq", "ie-osm-timestamp.txt"):
            shutil.copy(os.path.join(osm, name), tmp)
        for sid, p in d["pages"].items():
            cells = ["Toll Locations and Charges", p["name"], f"Location: {p['archived']}", p["heading"]] + p.get("columns", []) + [x for r in p["rows"] for x in r] + ["(end of the table)"] * 20
            open(os.path.join(tmp, f"ie-{sid}.html"), "w", encoding="utf-8").write("".join(f"<div>{html.escape(c)}</div>" for c in cells))
        ie.main(tmp, tmp)
        path = os.path.join(tmp, f"ie-{d['year']}-01-01.json")
        tb = json.load(open(path))
        tb["law"] += f" From TII's pages as the Internet Archive kept them, read in a browser into tools/history/browser/{os.path.basename(f)}."
        tb["sources"] = [{"title": f"TII: {p['name']} ({p['heading'].title()}), Internet Archive copy", "url": p["archived"]} for p in d["pages"].values()] + tb["sources"][1:]
        os.makedirs(out, exist_ok=True)
        json.dump(tb, open(os.path.join(out, os.path.basename(path)), "w"), ensure_ascii=False, indent=1)
        print(os.path.join(out, os.path.basename(path)), len(tb["toll_points"]), "plazas")


if __name__ == "__main__":
    main(*sys.argv[1:])
