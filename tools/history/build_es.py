"""Builds Spain's SEITT toll table for 2025 with tools/tables/es_seitt.py
from SEITT's 2025 tariff PDFs, still served on its document server
(tools/history/sources.json, es-seitt-2025-*), and the OpenStreetMap
extract the history workflow copies into fetched/osm. The AP-41's 2025
tariff isn't served any more nor archived, so the 2025 table has the
AP-36 and AP-7 Cartagena–Vera only; 2024 has no table (none of the 2024
PDFs is served or archived).

Usage: python3 build_es.py fetched/ out-dir"""
import glob, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import es_seitt  # noqa: E402

FILES = {"ap36": "es-seitt-2025-ap36", "ap7cv": "es-seitt-2025-ap7cv"}


def main(fetched, out):
    tmp = tempfile.mkdtemp()
    osm = next((d for d in (os.path.join(fetched, "osm"), fetched) if os.path.exists(os.path.join(d, "es-osm.geojsonseq"))), None)
    if osm is None:
        sys.exit("no es-osm.geojsonseq")
    for f in glob.glob(os.path.join(osm, "es-osm*")):
        shutil.copy(f, tmp)
    for k, sid in FILES.items():
        src = os.path.join(fetched, sid + ".pdf")
        if not os.path.exists(src):
            sys.exit(f"{sid} not fetched")
        dst = os.path.join(tmp, f"es-seitt-{k}.pdf")
        shutil.copy(src, dst)
        subprocess.run(["pdftotext", "-layout", dst, dst[:-4] + ".txt"], check=True)
        subprocess.run(["pdftotext", "-bbox", dst, dst[:-4] + ".bbox.html"], check=True)
    open(os.path.join(tmp, "absent.txt"), "w").write("es-seitt-ap41\n")
    es_seitt.main(tmp, tmp)
    path = os.path.join(tmp, "es-seitt-2025-01-01.json")
    tb = json.load(open(path))
    srcs = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    tb["sources"] = [{"title": srcs[sid]["what"], "url": srcs[sid]["url"]} for sid in FILES.values()] + [s for s in tb["sources"] if "openstreetmap" in s["title"].lower()]
    tb["law"] += " The AP-41's 2025 tariff isn't served or archived any more, so it isn't priced here."
    tb["tolled_roads"] = "AP-36 Ocaña – La Roda, AP-7 Cartagena – Vera (not the AP-41, whose 2025 tariff isn't available)."
    os.makedirs(out, exist_ok=True)
    json.dump(tb, open(os.path.join(out, os.path.basename(path)), "w"), ensure_ascii=False, indent=1)
    print(os.path.join(out, os.path.basename(path)), len(tb["closed_systems"]), "systems")


if __name__ == "__main__":
    main(*sys.argv[1:])
