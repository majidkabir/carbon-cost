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


def get(url):
    last = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(10)
    raise RuntimeError(f"{url}: {last}")


def capture(url, frm, to):
    q = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(
        {"url": url, "from": frm, "to": to, "output": "json", "fl": "timestamp,original,statuscode", "filter": "statuscode:200"})
    rows = json.loads(get(q) or b"[]")
    return rows[-1][:2] if len(rows) > 1 else None


def fetch(s, urls, out):
    d = os.path.join(out, "wb-" + s["set"])
    os.makedirs(d, exist_ok=True)
    manifest = []
    for sid in s["ids"]:
        url = s.get("urls", {}).get(sid) or urls[sid]
        try:
            c = capture(url, s["from"], s["to"])
            if not c:
                print("no capture", sid, url)
                manifest.append({"id": sid, "url": url, "capture": None})
                continue
            ts, orig = c
            body = get(f"https://web.archive.org/web/{ts}id_/{orig}")
            ext = ".pdf" if body[:4] == b"%PDF" else ".html"
            path = os.path.join(d, sid + ext)
            open(path, "wb").write(body)
            if ext == ".pdf":
                subprocess.run(["pdftotext", "-layout", path, path[:-4] + ".txt"], check=False)
            manifest.append({"id": sid, "url": url, "capture": ts, "archived": f"https://web.archive.org/web/{ts}/{orig}",
                             "size": len(body), "sha256": hashlib.sha256(body).hexdigest()})
            print(ts, len(body), sid)
        except Exception as e:
            print("ERROR", sid, e)
            manifest.append({"id": sid, "url": url, "error": str(e)})
    for f in glob.glob(os.path.join(out, "osm", "*")):
        shutil.copy(f, d)
    json.dump(manifest, open(os.path.join(d, "manifest.json"), "w"), indent=1)
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
                tb.setdefault("sources", []).append({"title": f"Internet Archive copy of {m['url']} ({m['capture'][:8]})", "url": m["archived"]})
        tb["law"] += f" Rebuilt from the Internet Archive's copies of these pages ({s['from'][:4]})."
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
            if not tb.get("valid_to") or tb["valid_to"] > end:
                tb["valid_to"] = end


def main(cfg, sources, out, data="rates/data"):
    urls = {s["id"]: s["url"] for s in json.load(open(sources, encoding="utf-8"))["sources"]}
    tables = []
    for s in json.load(open(cfg, encoding="utf-8"))["sets"]:
        d, manifest = fetch(s, urls, out)
        tables += build(s, d, manifest, out)
    # The same table from two sets (a page unchanged across years) is kept once.
    uniq = {}
    for name, tb in tables:
        uniq.setdefault(name, tb)
    tables = sorted(uniq.items())
    close(tables, data)
    os.makedirs(os.path.join(out, "tables"), exist_ok=True)
    for name, tb in tables:
        json.dump(tb, open(os.path.join(out, "tables", name), "w"), ensure_ascii=False, indent=1)
        print("table", name, tb["valid_from"], tb.get("valid_to"))


if __name__ == "__main__":
    main(*sys.argv[1:])
