"""Builds France's motorway toll tables before February 2026 with the
tools/fr pipeline (parse.py, stations.py, build.py) from the operators'
tariff documents of earlier years that the Internet Archive kept
(tools/history/sources.json, fr-<year>-*). French tariffs change each
1 February, so a table runs from 1 February to 31 January (the 2023
tariffs from 1 January 2024).

Only the documents archived are priced: the table names its operators.
The stations are placed as the current table's are, with the ministry's
toll station dataset, tools/fr/aliases.json and OpenStreetMap, from the
inputs the France data workflow last fetched (the fr-out branch, which the
history workflow copies into fetched/osm/fr).

Usage: python3 build_fr.py fetched/ out-dir"""
import hashlib, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, "..", "fr")
sys.path.insert(0, FR)
import build, parse, stations  # noqa: E402

# Per tariff year: the dates and the documents (source id, file name in the
# tools/fr layout, and its documents.json entry as for the current table).
YEARS = [
    {"tariffs": 2023, "valid_from": "2024-01-01", "valid_to": "2024-01-31", "docs": [
        ("fr-2023-aprr", "aprr/TARIFS_APRR.pdf", {"parser": "list", "operator": "APRR", "covers": "APRR network"}),
        ("fr-2023-area", "aprr/TARIFS_AREA.pdf", {"parser": "list_codes", "operator": "AREA", "covers": "AREA network"}),
        ("fr-2023-asf-guide", "vinci/Tarifs-guide-ASF-2023.pdf", {"parser": "grid", "operator": "ASF", "covers": "ASF network (its tariff guide's class grids)"}),
        ("fr-2023-cofiroute", "vinci/Tarifs-guide-Cofiroute-2023.pdf", {"parser": "list_roads", "operator": "Cofiroute", "covers": "Cofiroute network"}),
        ("fr-2023-aliae", "aliae/TARIFS_ALIAE.pdf", {"parser": "list", "operator": "ALIAE", "covers": "A79"}),
    ]},
    {"tariffs": 2024, "valid_from": "2024-02-01", "valid_to": "2025-01-31", "docs": [
        ("fr-2024-aprr-v2", "aprr/TARIFS_APRR.pdf", {"parser": "list", "operator": "APRR", "covers": "APRR network (the document's second version, of April 2024)"}),
        ("fr-2024-area", "aprr/TARIFS_AREA.pdf", {"parser": "list_codes", "operator": "AREA", "covers": "AREA network"}),
        (["fr-2024-asf-c3", "fr-2024-asf-c4"], ["vinci/C3-TARIFS-WEB-2024.pdf", "vinci/C4-TARIFS-WEB-2024.pdf"], {"parser": "grid", "operator": "ASF", "covers": "ASF network"}),
        ("fr-2024-escota", "vinci/Escota-Grilles-tarifaires-2024_provisoires.pdf", {"parser": "grid", "operator": "Escota", "covers": "Escota network (the grids published as provisional, pending the State's final approval)"}),
        ("fr-2024-aliae-v2", "aliae/TARIFS_ALIAE.pdf", {"parser": "list", "operator": "ALIAE", "covers": "A79 (the document's second version)"}),
        ("fr-2024-alienor", "alienor/TARIFS_A65.pdf", {"parser": "gares", "operator": "A'liénor", "covers": "A65 Langon-Pau"}),
    ]},
    {"tariffs": 2025, "valid_from": "2025-02-01", "valid_to": "2026-01-31", "docs": [
        ("fr-2025-aprr", "aprr/TARIFS_APRR.pdf", {"parser": "list", "operator": "APRR", "covers": "APRR network"}),
        ("fr-2025-area", "aprr/TARIFS_AREA.pdf", {"parser": "list_codes", "operator": "AREA", "covers": "AREA network"}),
        ("fr-2025-cofiroute", "vinci/Cofiroute-Guide-tarifaire-2025-V2.pdf", {"parser": "list_roads", "operator": "Cofiroute", "covers": "Cofiroute network (the guide's second version)"}),
        ("fr-2025-escota", "vinci/Escota-tarifs-2025-provisoires.pdf", {"parser": "grid", "operator": "Escota", "covers": "Escota network (the grids published as provisional, pending the State's final approval)"}),
    ]},
]

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    srcs = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    frin = next((d for d in (os.path.join(fetched, "osm", "fr"), os.path.join(fetched, "fr")) if os.path.exists(os.path.join(d, "osm-booths.geojsonseq"))), None)
    if frin is None:
        sys.exit("no France station inputs (osm/fr)")
    gares = sorted(f for f in os.listdir(os.path.join(frin, "stations")) if f.startswith("Gares-Peage_20") and "shp" not in f)[-1]
    for y in YEARS:
        tmp = tempfile.mkdtemp()
        manifest, docs = [], []
        for sids, names, d in y["docs"]:
            sids, names = ([sids], [names]) if isinstance(sids, str) else (sids, names)
            for sid, name in zip(sids, names):
                src = os.path.join(fetched, sid + ".pdf")
                if not os.path.exists(src):
                    sys.exit(f"{sid} not fetched")
                dst = os.path.join(tmp, name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst)
                subprocess.run(["pdftotext", "-layout", dst, dst[:-4] + ".txt"], check=True)
                manifest.append({"file": name, "url": srcs[sid]["url"], "sha256": sha(dst)})
            entry = dict(d)
            if d["parser"] == "grid":
                entry["files"] = names
            else:
                entry["file"], entry["url_from"] = names[0][:-4] + ".txt", names[0]
            docs.append(entry)
        json.dump({"files": manifest}, open(os.path.join(tmp, "manifest.json"), "w"))
        json.dump({"documents": docs}, open(os.path.join(tmp, "documents.json"), "w"))
        parse.main(os.path.join(tmp, "documents.json"), tmp, os.path.join(tmp, "pairs.csv"))
        stations.main(os.path.join(tmp, "pairs.csv"), os.path.join(frin, "stations", gares), os.path.join(FR, "aliases.json"),
                      os.path.join(frin, "osm-booths.geojsonseq"), os.path.join(tmp, "stations.json"))
        build.main(os.path.join(tmp, "pairs.csv"), os.path.join(tmp, "stations.json"), os.path.join(tmp, "manifest.json"), os.path.join(tmp, "fr.json"))
        tb = json.load(open(os.path.join(tmp, "fr.json"), encoding="utf-8"))
        vf = {s["title"].split(" from ")[1].split(" ")[0] for s in tb["sources"] if " tariffs from " in s["title"]}
        if vf != {f"{y['tariffs']}-02-01"}:
            sys.exit(f"{y['tariffs']}: documents valid from {vf}")
        ops = sorted({d["operator"] for _, _, d in y["docs"]})
        tb["valid_from"], tb["valid_to"] = y["valid_from"], y["valid_to"]
        tb["law"] = ("Code de la voirie routière art. L122-4 and décret n° 95-81; tariffs set yearly by the concession contracts, as published by each operator: "
                     f"their tariffs in force from 1 February {y['tariffs']}, as the Internet Archive kept them, for " + ", ".join(ops)
                     + ". The other operators' documents of that year weren't archived, so their motorways aren't priced. A trip pays the published entry-exit prices along its route, excluding 20% VAT. Stations placed with the ministry's toll station dataset (data.gouv.fr) and OpenStreetMap.")
        tb["closed_systems"][0]["law"] = tb["closed_systems"][0]["law"].replace("and the arrêtés of 28 January 2026", f"in force from 1 February {y['tariffs']}")
        tb["tolled_roads"] = "The conceded motorways of " + ", ".join(ops) + " (the others' tariffs of that year weren't archived)."
        tb["sources"] = [dict(s, title=s["title"].replace(" tariffs from ", " tariffs from ").replace(f"(sha256", "(Internet Archive copy, sha256")) if " tariffs from " in s["title"] else s for s in tb["sources"]]
        path = os.path.join(out, f"fr-{y['valid_from']}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
        print(path, ops, len(tb["closed_systems"][0]["prices"]), "pairs")
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main(*sys.argv[1:])
