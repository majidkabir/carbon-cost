"""Downloads the French toll sources listed in sources.json into an
output folder, with a manifest of what was fetched and when.

Usage: python3 fetch.py sources.json out/

For each operator: every page in "pages" (saved as text with its links,
without scripts, which can hold the site's own access tokens) and every PDF,
XLSX or CSV linked from those pages whose link or text mentions a tariff
(tarif, grille, péage, prix); PDFs are also converted to text with
pdftotext -layout. The toll stations dataset is fetched from data.gouv.fr
with its resources. manifest.json records each file's URL, sha256, size
and the fetch time, so a run can be compared with the next.
"""
import hashlib, html, json, os, re, subprocess, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "carbon-cost docs fetch (github.com/majidkabir/carbon-cost)"}
DOC = re.compile(r"\.(pdf|xlsx?|csv)(\?|#|$)", re.I)
WANT = re.compile(r"tarif|grille|p[ée]age|prix|classe", re.I)


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.headers.get("Content-Type", "")


def save(manifest, out, rel, url, data):
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
    manifest.append({"file": rel, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                     "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    if rel.lower().endswith(".pdf"):
        subprocess.run(["pdftotext", "-layout", path, path[:-4] + ".txt"], check=False)


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[-120:]


def main(src, out):
    s = json.load(open(src, encoding="utf-8"))
    manifest, errors = [], []
    for op in s["operators"]:
        seen = set()
        for i, page in enumerate(op["pages"]):
            try:
                data, _ = get(page)
            except Exception as e:
                errors.append({"operator": op["id"], "url": page, "error": str(e)})
                continue
            text = data.decode("utf-8", "replace")
            text = re.sub(r"<(script|style|noscript)\b.*?</\1>", "", text, flags=re.S | re.I)
            links = [f"{re.sub(r'<[^>]+>|\s+', ' ', html.unescape(m.group(2))).strip()} <{urllib.parse.urljoin(page, html.unescape(m.group(1)))}>"
                     for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I)]
            body = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
            save(manifest, out, f"{op['id']}/page{i}.txt", page, (body + "\n\nLINKS\n" + "\n".join(links)).encode())
            for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I):
                href, label = html.unescape(m.group(1)), re.sub(r"<[^>]+>|\s+", " ", m.group(2))
                url = urllib.parse.urljoin(page, href)
                if not DOC.search(url) or not (WANT.search(url) or WANT.search(label)) or url in seen:
                    continue
                seen.add(url)
                try:
                    d, _ = get(url)
                    save(manifest, out, f"{op['id']}/{safe(urllib.parse.unquote(url.split('/')[-1].split('?')[0]))}", url, d)
                except Exception as e:
                    errors.append({"operator": op["id"], "url": url, "error": str(e)})
    try:
        meta, _ = get(s["stations"])
        save(manifest, out, "stations/dataset.json", s["stations"], meta)
        for r in json.loads(meta)["resources"]:
            try:
                d, _ = get(r["url"])
                save(manifest, out, "stations/" + safe(r["title"] or r["url"].split("/")[-1]), r["url"], d)
            except Exception as e:
                errors.append({"operator": "stations", "url": r["url"], "error": str(e)})
    except Exception as e:
        errors.append({"operator": "stations", "url": s["stations"], "error": str(e)})
    json.dump({"files": manifest, "errors": errors}, open(os.path.join(out, "manifest.json"), "w"), ensure_ascii=False, indent=1)
    print(len(manifest), "files,", len(errors), "errors")
    for e in errors:
        print("error", e["operator"], e["url"], e["error"][:120])


if __name__ == "__main__":
    main(*sys.argv[1:])
