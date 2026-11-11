"""Keeps Internet Archive copies from the last run: a capture never
changes, and the archive often refuses the workflow's requests. For each
history source with a Wayback URL (web.archive.org/web/<capture>id_/...)
that this run failed to fetch, the copy the last run fetched (in prev/,
from the history-out branch) is used, with its manifest entry.

Usage: python3 reuse.py tools/history/sources.json out/ prev/"""
import glob, json, os, shutil, sys


def main(sources, out, prev):
    ids = {s["id"]: s["url"] for s in json.load(open(sources, encoding="utf-8"))["sources"] if "web.archive.org/web/" in s["url"]}
    man = json.load(open(os.path.join(out, "manifest.json")))
    try:
        old = {f["file"]: f for f in json.load(open(os.path.join(prev, "manifest.json")))["files"]}
    except FileNotFoundError:
        return
    cur = {f["file"]: f for f in man["files"]}
    for sid, url in ids.items():
        if any(f.startswith(sid + ".") and v.get("status") == 200 for f, v in cur.items()):
            continue
        hit = [v for f, v in old.items() if f.startswith(sid + ".") and v.get("status") == 200 and v.get("url") == url]
        if not hit:
            continue
        for p in glob.glob(os.path.join(out, sid + ".*")):
            os.remove(p)
        for p in glob.glob(os.path.join(prev, sid + ".*")):
            shutil.copy(p, out)
        man["files"] = [f for f in man["files"] if not f["file"].startswith(sid + ".")] + [dict(hit[0], reused=True)]
        print("reused", sid)
    json.dump(man, open(os.path.join(out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
