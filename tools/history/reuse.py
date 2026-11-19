"""Keeps copies from the last run. For each history source this run
failed to fetch (any status but 200), the copy the last run fetched from
the same URL (in prev/, from the history-out branch) is used, with its
manifest entry marked reused: an Internet Archive capture never changes,
and the archive and some law portals (wetten.overheid.nl) at times refuse
the workflow's requests.

Usage: python3 reuse.py tools/history/sources.json out/ prev/

Before the fetch, "python3 reuse.py todo sources.json prev/ todo.json"
writes the sources less those Wayback copies the last run has, so the
fetch doesn't ask the archive for them again."""
import glob, json, os, shutil, sys


def main(sources, out, prev):
    ids = {s["id"]: s["url"] for s in json.load(open(sources, encoding="utf-8"))["sources"]}
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


def todo(sources, prev, out):
    d = json.load(open(sources, encoding="utf-8"))
    try:
        old = {f["file"]: f for f in json.load(open(os.path.join(prev, "manifest.json")))["files"]}
    except FileNotFoundError:
        old = {}
    have = {s["id"] for s in d["sources"] if "web.archive.org/web/" in s["url"]
            and any(f.startswith(s["id"] + ".") and v.get("status") == 200 and v.get("url") == s["url"] for f, v in old.items())}
    d["sources"] = [s for s in d["sources"] if s["id"] not in have]
    json.dump(d, open(out, "w"), ensure_ascii=False, indent=1)
    print(len(have), "archived copies kept from the last run;", len(d["sources"]), "sources to fetch")


if __name__ == "__main__":
    if sys.argv[1] == "todo":
        todo(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
