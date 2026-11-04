"""Fetches the pages in sources.json into out-dir, as fetched, with a
manifest (URL, sha256, size, fetch time, HTTP status, errors).

Usage: python3 fetch.py sources.json out-dir

For the CNAIR page it also follows the resource URLs the page's scripts
use (Liferay portlet resource requests, p_p_lifecycle=2), and asks the
TollRo one for the active pricing offer (rest_path
/pricing-offers/active-pricing-offer, productClass PER_KM).
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


def main(src, out):
    os.makedirs(out, exist_ok=True)
    manifest, errors = [], []
    for s in json.load(open(src, encoding="utf-8"))["sources"]:
        try:
            status, body = get(s["url"])
            save(out, manifest, s["id"] + ".html", s["url"], status, body)
            if s["id"] == "ro-tollro":
                tollro(out, manifest, s["url"], body)
        except Exception as e:
            errors.append(f"{s['id']}: {e}")
            print("ERROR", s["id"], e)
    json.dump({"files": manifest, "errors": errors}, open(os.path.join(out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
