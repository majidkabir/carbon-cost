"""Fetches the pages in sources.json into out-dir, as fetched, with a
manifest (URL, sha256, size, fetch time, HTTP status, errors).

Usage: python3 fetch.py sources.json out-dir

For the CNAIR page it also follows the resource URLs the page's scripts
use (Liferay portlet resource requests, p_p_lifecycle=2), and asks the
TollRo one for the active pricing offer (rest_path
/pricing-offers/active-pricing-offer, productClass PER_KM).

The Nemzeti Jogszabálytár (njt.jog.gov.hu) sends long texts in parts:
the page holds placeholders (data-show-order .. data-last-show-order)
that its script fills from /ajax/njtGetBlock.json, given the document id
and the placeholder's range. Those parts are fetched too, as
<id>-block-<n>.html.

Riigi Teataja (riigiteataja.ee) pages are built by script from its public
API: /public-api/api/v1/akt/<id>?leiaKehtiv=true names the version in
force (kehtivId, saved as <id>.json), whose text is
/public-api/api/v1/akt/<kehtivId>/blob-html (saved as <id>-text.html).

The NVDB API (nvdbapiles.atlas.vegvesen.no) pages its results: each JSON
names the next page in metadata.neste.href; those pages are fetched too,
as <id>-<n>.json, until a page returns no objects.
"""
import hashlib, html, json, os, re, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "carbon-cost tables fetch (github.com/majidkabir/carbon-cost)", "Accept-Language": "en,da,ro,hu"}


def get(url, accept=None):
    h = dict(UA)
    if accept:
        h["Accept"] = accept
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            last = e
            time.sleep(5)
    raise RuntimeError(f"{url}: {last}")


def save(out, manifest, name, url, status, body):
    with open(os.path.join(out, name), "wb") as f:
        f.write(body)
    manifest.append({"file": name, "url": url, "status": status, "size": len(body),
                     "sha256": hashlib.sha256(body).hexdigest(), "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    print(status, len(body), name, url)


def tollro(out, manifest, page_url, page):
    text = html.unescape(page.decode("utf-8", "replace"))
    urls = sorted(set(u.replace("\\u0026", "&").replace("\\/", "/") for u in re.findall(r"https?://[^\"'\s<>]*p_p_lifecycle=2[^\"'\s<>]*", text)))
    urls += sorted(set(urllib.parse.urljoin(page_url, u.replace("\\u0026", "&")) for u in re.findall(r"[\"'](/web/guest/[^\"'\s<>]*p_p_lifecycle=2[^\"'\s<>]*)", text)))
    with open(os.path.join(out, "ro-resource-urls.txt"), "w") as f:
        f.write("\n".join(urls) + "\n")
    tried = set()
    for u in urls:
        if "digitalizeportlet" not in u:
            continue
        base = re.sub(r"&(productClass|lang|rest_path|rest_method)=[^&]*", "", u)
        q = base + ("&" if "?" in base else "?") + urllib.parse.urlencode(
            {"productClass": "PER_KM", "lang": "ro", "rest_path": "/pricing-offers/active-pricing-offer", "rest_method": "GET"})
        if q in tried:
            continue
        tried.add(q)
        status, body = get(q, "application/json")
        save(out, manifest, f"ro-active-pricing-offer-{len(tried)}.json", q, status, body)


def njt(out, manifest, sid, page_url, page):
    doc = page_url.rstrip("/").rsplit("/", 1)[1]
    text = page.decode("utf-8", "replace")
    blocks = re.findall(r'data-show-order="(\d+)" data-last-show-order="(\d+)"', text)
    for n, (a, b) in enumerate(blocks, 1):
        body = json.dumps({"documentId": doc, "data": [{"start": int(a), "last": int(b)}]}).encode()
        url = urllib.parse.urljoin(page_url, "/ajax/njtGetBlock.json")
        req = urllib.request.Request(url, data=body, headers={**UA, "Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest", "Referer": page_url})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, resp = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, resp = e.code, e.read()
        save(out, manifest, f"{sid}-block-{n}.html", url + f" (POST start {a} last {b})", status, resp)


def riigiteataja(out, manifest, sid, body):
    d = json.loads(body)
    url = f"https://www.riigiteataja.ee/public-api/api/v1/akt/{d['kehtivId']}/blob-html"
    status, text = get(url)
    save(out, manifest, f"{sid}-text.html", url, status, text)


def nvdb(out, manifest, sid, body):
    n = 1
    while n < 200:
        d = json.loads(body)
        nxt = (d.get("metadata") or {}).get("neste", {}).get("href")
        if not d.get("objekter") or not nxt:
            return
        n += 1
        status, body = get(nxt, "application/json")
        save(out, manifest, f"{sid}-{n}.json", nxt, status, body)


def main(src, out):
    os.makedirs(out, exist_ok=True)
    manifest, errors = [], []
    for s in json.load(open(src, encoding="utf-8"))["sources"]:
        try:
            status, body = get(s["url"], "application/json" if "nvdbapiles" in s["url"] else None)
            ext = os.path.splitext(urllib.parse.urlparse(s["url"]).path)[1].lower()
            if "riigiteataja.ee/public-api/" in s["url"] or "nvdbapiles" in s["url"]:
                ext = ".json"
            save(out, manifest, s["id"] + (ext if ext in (".pdf", ".jpg", ".png", ".json") else ".html"), s["url"], status, body)
            if "riigiteataja.ee/public-api/" in s["url"]:
                riigiteataja(out, manifest, s["id"], body)
            if "nvdbapiles" in s["url"] and status == 200:
                nvdb(out, manifest, s["id"], body)
            if s["id"] == "ro-tollro":
                tollro(out, manifest, s["url"], body)
            if "njt.jog.gov.hu/jogszabaly/" in s["url"]:
                njt(out, manifest, s["id"], s["url"], body)
        except Exception as e:
            errors.append(f"{s['id']}: {e}")
            print("ERROR", s["id"], e)
    json.dump({"files": manifest, "errors": errors}, open(os.path.join(out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
