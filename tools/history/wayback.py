"""Fetch earlier copies of official pages from the Wayback Machine and
rebuild rate tables from them with the tools/tables builders.

    python3 tools/history/wayback.py tools/history/wayback.json tools/tables/sources.json out

For each set in wayback.json and each id, it asks the Wayback CDX API for
the last capture with HTTP 200 between the set's from and to dates, saves
the unmodified copy (the id_ form) as out/wb-<set>/<id>.<ext> and records
it in out/wb-<set>/manifest.json. OpenStreetMap extracts the builders need
are copied from out/osm (the workflow puts them there). Then it runs the
set's builders with fetched=out/wb-<set>, writes their tables to
out/tables, and replaces each source URL a table names with the archived
copy it was built from. A table without valid_to gets the day before the
next table for the same file prefix (built here or in rates/data)."""
import datetime
import glob
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
UA = {"User-Agent": "carbon-cost history (github.com/majidkabir/carbon-cost)"}


# Pages a bot check or an error served instead of the content.
NOT_CONTENT = re.compile(rb"Please wait while your request is being verified|One moment, please|Just a moment\.\.\.|Access denied", re.I)


def get(url):
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:
            last = e
            # The archive refuses connections when asked too fast.
            time.sleep(15 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def captures(url, frm, to, match=None, regex=None, collapse=None):
    """Captures with HTTP 200 between frm and to, oldest first, as
    (timestamp, original URL); match="prefix" takes every URL under url,
    regex keeps those whose URL matches it."""
    q = {"url": url, "from": frm, "to": to, "output": "json", "fl": "timestamp,original,statuscode", "filter": ["statuscode:200"]}
    if match:
        q["matchType"] = match
    if regex:
        q["filter"].append("original:" + regex)
    if collapse:
        q["collapse"] = collapse
        q["limit"] = 3000
    rows = json.loads(get("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(q, doseq=True)) or b"[]")
    time.sleep(3)
    return [tuple(r[:2]) for r in rows[1:]]


def fetch(s, urls, out):
    # A set with "dir" saves its copies there (under out) for the
    # build_*.py scripts, which read out/.
    d = os.path.join(out, s.get("dir", "wb-" + s["set"]))
    os.makedirs(d, exist_ok=True)
    manifest = []
    for sid in s["ids"]:
        # An id's URL, or where its earlier copies are: {"url", "match",
        # "regex"} (the latest URL matching).
        where = s.get("urls", {}).get(sid) or urls[sid]
        if isinstance(where, str):
            where = {"url": where}
        url = where["url"]
        must = s.get("must", {}).get(sid)
        try:
            body = None
            for ts, orig in reversed(captures(url, where.get("from", s["from"]), where.get("to", s["to"]), where.get("match"), where.get("regex"))[-8:]):
                b = get(f"https://web.archive.org/web/{ts}id_/{orig}")
                time.sleep(3)
                if NOT_CONTENT.search(b[:20000]) or (must and not re.search(must.encode(), b)):
                    print("not the content", sid, ts)
                    continue
                body = b
                break
            if body is None:
                print("no capture", sid, url)
                manifest.append({"id": sid, "url": url, "capture": None})
                continue
            ext = ".pdf" if body[:4] == b"%PDF" else ".html"
            path = os.path.join(d, sid + ext)
            open(path, "wb").write(body)
            if ext == ".pdf":
                subprocess.run(["pdftotext", "-layout", path, path[:-4] + ".txt"], check=False)
                subprocess.run(["pdftotext", "-bbox", path, path[:-4] + ".bbox.html"], check=False)
            manifest.append({"id": sid, "url": url, "capture": ts, "original": orig, "archived": f"https://web.archive.org/web/{ts}/{orig}",
                             "size": len(body), "sha256": hashlib.sha256(body).hexdigest()})
            print(ts, len(body), sid, flush=True)
        except Exception as e:
            print("ERROR", sid, e)
            manifest.append({"id": sid, "url": url, "error": str(e)})
    if "dir" not in s:
        for f in glob.glob(os.path.join(out, "osm", "*")):
            shutil.copy(f, d)
    json.dump(manifest, open(os.path.join(out, f"wb-{s['set']}-manifest.json"), "w"), indent=1)
    return d, manifest


def build(s, d, manifest, out):
    tmp = os.path.join(out, "wb-" + s["set"] + "-tables")
    os.makedirs(tmp, exist_ok=True)
    for b in s["builders"]:
        try:
            importlib.import_module(b).main(d, tmp)
        except BaseException as e:
            print(f"::error title=wayback {s['set']} {b}::{e!r}")
    arch = {m["url"]: m["archived"] for m in manifest if m.get("archived")}
    caps = [m for m in manifest if m.get("archived")]
    made = []
    for f in sorted(glob.glob(os.path.join(tmp, "*.json"))):
        tb = json.load(open(f))
        for src in tb.get("sources", []):
            # A source names the page its builder read; point it at the copy.
            for u, a in arch.items():
                if src.get("url") and src["url"].rstrip("/") == u.rstrip("/"):
                    src["url"] = a
        have = {src.get("url") for src in tb.get("sources", [])}
        for m in caps:
            if m["id"].split("-")[0] == tb["country"].lower() and m["archived"] not in have:
                tb.setdefault("sources", []).append({"title": f"Internet Archive copy of {m['original']} ({m['capture'][:8]})", "url": m["archived"]})
        tb["law"] += f" Rebuilt from the Internet Archive's copies of these pages ({s['from'][:4]})."
        # A table the set ends earlier: [valid_to, why, source URL].
        end = s.get("valid_to", {}).get(os.path.basename(f))
        if end:
            tb["valid_to"], why, url = end
            tb["law"] += " " + why
            tb["sources"].append({"title": why.rstrip("."), "url": url})
        made.append((os.path.basename(f), tb))
    return made


def prefix(name):
    return re.sub(r"-\d{4}-\d\d-\d\d\.json$", "", name)


def close(tables, data):
    starts = {}
    for name, tb in tables + [(os.path.basename(f), json.load(open(f))) for f in glob.glob(os.path.join(data, "*.json"))]:
        starts.setdefault(prefix(name), set()).add(tb["valid_from"])
    for name, tb in tables:
        nxt = sorted(v for v in starts[prefix(name)] if v > tb["valid_from"])
        if nxt:
            end = (datetime.date.fromisoformat(nxt[0]) - datetime.timedelta(days=1)).isoformat()
            if not tb.get("valid_to") or tb["valid_to"] > end:  # never later than the next table
                tb["valid_to"] = end


def main(cfg, sources, out, data="rates/data"):
    urls = {s["id"]: s["url"] for s in json.load(open(sources, encoding="utf-8"))["sources"]}
    tables = []
    conf = json.load(open(cfg, encoding="utf-8"))
    only = [x for x in os.environ.get("WAYBACK_SETS", "").split(",") if x]
    for s in conf["sets"]:
        if only and s["set"] not in only:
            continue
        d, manifest = fetch(s, urls, out)
        if s.get("builders"):
            tables += build(s, d, manifest, out)
        if "dir" not in s:
            for f in glob.glob(os.path.join(out, "osm", "*")):
                os.remove(os.path.join(d, os.path.basename(f)))
        # Written after each set, so a run cut short keeps what it built.
        write(tables, out, data)
    # Probes list the archived URLs under a prefix, to find where a page
    # was before it moved; they build nothing.
    if only:
        return
    with open(os.path.join(out, "wayback-probes.txt"), "w") as f:
        for p in conf.get("probes", []):
            try:
                for ts, orig in captures(p["url"], p.get("from", "2023"), p.get("to", "2026"), "prefix", p.get("regex"), "urlkey"):
                    f.write(f"{ts} {orig}\n")
                f.flush()
            except Exception as e:
                f.write(f"ERROR {p['url']}: {e}\n")


def write(tables, out, data):
    # The same table from two sets (a page unchanged across years) is kept once.
    uniq = {}
    for name, tb in tables:
        uniq.setdefault(name, tb)
    tables = sorted(uniq.items())
    close(tables, data)
    os.makedirs(os.path.join(out, "tables"), exist_ok=True)
    for name, tb in tables:
        json.dump(tb, open(os.path.join(out, "tables", name), "w"), ensure_ascii=False, indent=1)
        print("table", name, tb["valid_from"], tb.get("valid_to"), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
