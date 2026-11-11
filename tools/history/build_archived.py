"""Rebuilds rate tables for past years with the tools/tables builders, from
the official pages and PDFs as the Internet Archive kept them. The history
sources (tools/history/sources.json) name each copy by its Wayback URL
(https://web.archive.org/web/<capture>id_/<original URL>), so the workflow
fetches exactly those bytes; tools/history/archived.json says which copies
make each builder's input files (several copies are joined in order).

Usage: python3 build_archived.py fetched/ out-dir

The builder runs with the OpenStreetMap extracts the workflow copies into
fetched/osm. Each table built names the archived copies it was built from,
and gets valid_to the day before the next table for the same file prefix
(here or in rates/data) when it has none or a later one."""
import datetime, glob, importlib, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
WB = re.compile(r"https://web\.archive\.org/web/(\d{14})id_/(.+)")


def fetched_file(fetched, sid):
    return next((p for p in sorted(glob.glob(os.path.join(fetched, sid + ".*"))) if not p.endswith((".txt", ".bbox.html"))), None)


def prefix(name):
    return re.sub(r"-\d{4}-\d\d-\d\d\.json$", "", name)


def main(fetched, out, data=os.path.join(ROOT, "rates", "data")):
    srcs = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    made = []
    for b in json.load(open(os.path.join(HERE, "archived.json"), encoding="utf-8"))["builds"]:
        tmp = tempfile.mkdtemp()
        for f in glob.glob(os.path.join(fetched, "osm", "*")):
            shutil.copy(f, tmp)
        copies, ok = [], True
        for target, ids in b["files"].items():
            parts = []
            for sid in ids:
                p = fetched_file(fetched, sid)
                if p is None:
                    print(f"::warning title=archived {b['builder']} {b['year']}::{sid} not fetched")
                    ok = False
                    break
                parts.append(open(p, "rb").read())
                ts, orig = WB.match(srcs[sid]["url"]).groups()
                if ts[:4] != b["year"]:
                    sys.exit(f"{sid}: captured {ts}, not in {b['year']}")
                copies.append((orig, f"https://web.archive.org/web/{ts}/{orig}", ts))
            if not ok:
                break
            open(os.path.join(tmp, target), "wb").write(b"\n".join(parts))
            if target.endswith(".pdf"):
                os.system(f"pdftotext -layout '{os.path.join(tmp, target)}' '{os.path.join(tmp, target[:-4])}.txt'")
                os.system(f"pdftotext -bbox '{os.path.join(tmp, target)}' '{os.path.join(tmp, target[:-4])}.bbox.html'")
        if not ok:
            continue
        before = set(os.listdir(tmp))
        try:
            importlib.import_module(b["builder"]).main(tmp, tmp)
        except BaseException as e:
            print(f"::error title=archived {b['builder']} {b['year']}::{e!r}")
            continue
        for f in sorted(set(os.listdir(tmp)) - before):
            if not f.endswith(".json"):
                continue
            tb = json.load(open(os.path.join(tmp, f)))
            if not tb["valid_from"].startswith(b["year"]):
                print(f"::error title=archived {b['builder']} {b['year']}::{f} is from {tb['valid_from']}")
                continue
            for s in tb["sources"]:
                for orig, arch, _ in copies:
                    if s["url"].rstrip("/") == orig.rstrip("/"):
                        s["url"] = arch
            have = {s["url"] for s in tb["sources"]}
            tb["sources"] += [{"title": f"Internet Archive copy of {orig} ({ts[:8]})", "url": arch} for orig, arch, ts in copies if arch not in have]
            tb["law"] += f" Built from the Internet Archive's copies of the {b['year']} pages." + (" " + b["note"] if b.get("note") else "")
            made.append((f, tb))
    starts = {}
    for name, tb in made + [(os.path.basename(f), json.load(open(f))) for f in glob.glob(os.path.join(data, "*.json"))]:
        starts.setdefault(prefix(name), set()).add(tb["valid_from"])
    os.makedirs(out, exist_ok=True)
    for name, tb in made:
        nxt = sorted(v for v in starts[prefix(name)] if v > tb["valid_from"])
        if nxt:
            end = (datetime.date.fromisoformat(nxt[0]) - datetime.timedelta(days=1)).isoformat()
            if not tb.get("valid_to") or tb["valid_to"] > end:
                tb["valid_to"] = end
        json.dump(tb, open(os.path.join(out, name), "w"), ensure_ascii=False, indent=1)
        print(os.path.join(out, name), tb["valid_from"], tb.get("valid_to"))


if __name__ == "__main__":
    main(*sys.argv[1:])
