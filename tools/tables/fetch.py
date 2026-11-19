"""Fetches the pages in sources.json into out-dir, as fetched, with a
manifest (URL, sha256, size, fetch time, HTTP status, errors).

Usage: python3 fetch.py sources.json out-dir

A source may name what its answer must hold ("expect", strings); one
without them is asked for again, then counts as failed.

For the CNAIR page it also follows the resource URLs the page's scripts
use (Liferay portlet resource requests, p_p_lifecycle=2), and asks the
TollRo one for the active pricing offer (rest_path
/pricing-offers/active-pricing-offer, productClass PER_KM).

The Nemzeti Jogszabálytár (njt.jog.gov.hu) sends long texts in parts:
the page holds placeholders (data-show-order .. data-last-show-order)
that its script fills from /ajax/njtGetBlock.json, given the document id
and the placeholder's range. Those parts are fetched too, as
<id>-block-<n>.html.

PISRS (pisrs.si) answers from its API: /api/rezultat/... as JSON (saved
as <id>.json), /api/datoteke/integracije/<n> with the file (a PDF is saved
as <id>.pdf).

Uradni list (uradni-list.si) pages link their annexes as PDFs under
/files/; those are fetched too, as <id>-att-<n>.pdf.

Riigi Teataja (riigiteataja.ee) pages are built by script from its public
API: /public-api/api/v1/akt/<id>?leiaKehtiv=true names the version in
force (kehtivId, saved as <id>.json), whose text is
/public-api/api/v1/akt/<kehtivId>/blob-html (saved as <id>-text.html).

The NVDB API (nvdbapiles.atlas.vegvesen.no) pages its results: each JSON
names the next page in metadata.neste.href; those pages are fetched too,
as <id>-<n>.json, until a page returns no objects. For toll stations
(object type 45) the road link sequences they are placed on are fetched
as well, 50 at a time from /vegnett/api/v4/veglenkesekvenser?ider=...
(as <id>-links-<n>.json): their geometry runs in the road's metering
direction, which a station's charged direction refers to.

Scandlines' freight pages (freight.scandlines.com) link their PDFs, whose
names carry a hash that changes with each new edition: the tariffs page's
freight tariffs are saved as <id>-<the file's name, less the hash>.pdf
(e.g. scl-tariffs-scandlines-freight-tariff-2026-germany-denmark-10m-2026-01-01-until-recall.pdf),
the surcharges page's monthly notices (English) as <id>-<yyyy>-<mm>.pdf.

POLSCA Baltic Ferries' documents pages on unityline.eu link their PDFs
(freight tariffs, BES and ETS announcements): saved as <id>-<the file's
name, lower case>.pdf (e.g. polsca-tariff-polsca-freight-tariff-22.06.2026.pdf).
"""
import gzip, hashlib, html, json, os, re, sys, threading, time, urllib.parse, urllib.request

UA = {"User-Agent": "carbon-cost tables fetch (github.com/majidkabir/carbon-cost)", "Accept-Language": "en,da,ro,hu"}


def read(req):
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def within(f, seconds):
    """f() in a daemon thread, given up after seconds (the socket timeout
    is per read, so a server that trickles could hold a run for hours)."""
    box = {}

    def run():
        try:
            box["v"] = f()
        except BaseException as e:  # noqa: BLE001  (re-raised below)
            box["e"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"no answer within {seconds} s")
    if "e" in box:
        raise box["e"]
    return box["v"]


def get(url, accept=None, tries=3, pause=5):
    h = dict(UA)
    if accept:
        h["Accept"] = accept
    if "nvdbapiles" in url:
        h["X-Client"] = "carbon-cost tables fetch"  # the NVDB API asks clients to name themselves
    last = None
    for i in range(tries):
        try:
            status, body = within(lambda: read(urllib.request.Request(url, headers=h)), 300)
            # Some servers send gzip unasked.
            if body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            return status, body
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:
            last = e
            if i + 1 < tries:
                time.sleep(pause * (i + 1))
    raise RuntimeError(f"{url}: {last}")


# Guards the manifest and the error list: the Overpass queries are fetched
# on threads of their own (overpass_all).
LOCK = threading.Lock()


def save(out, manifest, name, url, status, body):
    with open(os.path.join(out, name), "wb") as f:
        f.write(body)
    with LOCK:
        manifest.append({"file": name, "url": url, "status": status, "size": len(body),
                         "sha256": hashlib.sha256(body).hexdigest(), "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        print(status, len(body), name, url, flush=True)


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
    # The act's annexes (lisa) are PDFs it links.
    for k, a in enumerate(sorted(set(re.findall(r"/aktilisa/[0-9/]+[^\"'#<>\s]*\.pdf", text.decode("utf-8", "replace")))), 1):
        u = "https://www.riigiteataja.ee" + a
        status, b = get(u)
        save(out, manifest, f"{sid}-lisa-{k}.pdf", u, status, b)


def nvdb(out, manifest, sid, url, body):
    n, links = 1, set()
    while n < 200:
        d = json.loads(body)
        for o in d.get("objekter") or []:
            for st in (o.get("lokasjon") or {}).get("stedfestinger") or []:
                if st.get("veglenkesekvensid"):
                    links.add(st["veglenkesekvensid"])
        nxt = (d.get("metadata") or {}).get("neste", {}).get("href")
        if not d.get("objekter") or not nxt:
            break
        n += 1
        status, body = get(nxt, "application/json")
        save(out, manifest, f"{sid}-{n}.json", nxt, status, body)
    if "/vegobjekter/45" not in url:
        return
    links = sorted(links)
    for k in range(0, len(links), 50):
        q = "https://nvdbapiles.atlas.vegvesen.no/vegnett/api/v4/veglenkesekvenser?srid=4326&ider=" + ",".join(map(str, links[k:k + 50]))
        status, b = get(q, "application/json")
        save(out, manifest, f"{sid}-links-{k // 50 + 1}.json", q, status, b)


def uradni_list(out, manifest, sid, page_url, page):
    # A Uradni list page links its annexes (Priloga) as PDFs under /files/;
    # each is saved as <id>-att-<n>.pdf, in page order.
    text = html.unescape(page.decode("utf-8", "replace"))
    seen = []
    for u in re.findall(r"""href=["']([^"']*/files/RS_[^"']+\.pdf)["']""", text, re.I):
        u = urllib.parse.urljoin(page_url, u)
        if u not in seen:
            seen.append(u)
    for n, u in enumerate(seen, 1):
        status, body = get(u)
        save(out, manifest, f"{sid}-att-{n}.pdf", u, status, body)


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def scandlines(out, manifest, sid, page_url, page):
    text = html.unescape(page.decode("utf-8", "replace"))
    seen = {}
    for u in re.findall(r"""href=["']([^"']+\.pdf)(?:\?[^"']*)?["']""", text):
        u = urllib.parse.urljoin(page_url, u)
        name = os.path.basename(urllib.parse.urlparse(u).path)
        m = re.match(r"(\d\d)_Scandlines_surcharges_([A-Za-z]+)_(\d{4})_ENG_[0-9a-f]+\.pdf$", name)
        if m and m.group(2) in MONTHS:
            seen.setdefault(f"{sid}-{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}.pdf", u)
            continue
        m = re.match(r"((?:Scandlines|Oresundslinjen)_Freight_Tariff_.+?)_[0-9a-f]{8,}\.pdf$", name)
        if m:
            seen.setdefault(f"{sid}-" + m.group(1).lower().replace("_", "-") + ".pdf", u)
    for name, u in sorted(seen.items()):
        status, body = get(u)
        save(out, manifest, name, u, status, body)


def polsca(out, manifest, sid, page_url, page):
    """The PDFs a POLSCA Baltic Ferries documents page on unityline.eu links
    (freight tariffs, surcharge announcements), saved as <id>-<file name,
    lower case>.pdf."""
    text = html.unescape(page.decode("utf-8", "replace"))
    seen = {}
    for u in re.findall(r"""href=["']([^"']*/__data/assets/pdf_file/[^"']+\.pdf)(?:\?[^"']*)?["']""", text):
        u = urllib.parse.urljoin(page_url, u)
        name = os.path.basename(urllib.parse.urlparse(u).path)
        seen.setdefault(f"{sid}-" + re.sub(r"[^a-z0-9.]+", "-", name.lower()), u)
    for name, u in sorted(seen.items()):
        status, body = get(u)
        save(out, manifest, name, u, status, body)


# Overpass instances serving the same OpenStreetMap data: a query goes to
# its own first, then to the others when that one can't be reached, is
# busy (429/502/503/504, retried after 30 and 60 s) or fails the query.
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]


def ask_overpass(url, prefer=None):
    """An Overpass query's answer, from the first instance that gives one: (status, body, url asked).
    A query written for overpass-api.de goes to `prefer` first when given; one
    written for another instance goes to that one first."""
    base, query = url.split("?", 1)
    first = prefer if prefer and base == OVERPASS[0] else base
    last = None
    for host in [first] + [h for h in OVERPASS if h != first]:
        for wait in (0, 30, 60, 120) if host == first else (0, 30):
            time.sleep(wait)
            try:
                status, body = get(host + "?" + query, tries=1)
            except Exception as e:
                last = f"{host}: {e}"
                break
            if status == 200 and not overpass_failed(status, body):
                return status, body, host + "?" + query
            last = f"{host}: {status} " + ((json.loads(body).get("remark") or "")[:200] if overpass_failed(status, body) else "")
            if status not in (429, 502, 503, 504) and not overpass_failed(status, body):
                break
    raise RuntimeError(f"Overpass: no instance answered (last: {last})")


def overpass_failed(status, body):
    if status != 200:
        return False
    try:
        d = json.loads(body)
    except ValueError:
        return False
    # A remark with elements is an answer cut short (a runtime error or a
    # timeout part way): incomplete, so failed too.
    r = d.get("remark") or ""
    return bool(r) and (not d.get("elements") or "error" in r.lower() or "timed out" in r.lower())


def store(out, manifest, s, status, body, asked):
    """Saves a source's answer (and what it leads to) under its id."""
    ext = os.path.splitext(urllib.parse.urlparse(s["url"]).path)[1].lower()
    if "riigiteataja.ee/public-api/" in s["url"] or "nvdbapiles" in s["url"] or "pisrs.si/api/rezultat/" in s["url"] or "/api/interpreter" in s["url"]:
        ext = ".json"
    if body[:4] == b"%PDF":
        ext = ".pdf"
    save(out, manifest, s["id"] + (ext if ext in (".pdf", ".jpg", ".png", ".json", ".csv") else ".html"), asked, status, body)
    if "riigiteataja.ee/public-api/" in s["url"]:
        riigiteataja(out, manifest, s["id"], body)
    if "nvdbapiles" in s["url"] and status == 200:
        nvdb(out, manifest, s["id"], s["url"], body)
    if s["id"] == "ro-tollro":
        tollro(out, manifest, s["url"], body)
    if "njt.jog.gov.hu/jogszabaly/" in s["url"]:
        njt(out, manifest, s["id"], s["url"], body)
    if "uradni-list.si/glasilo-uradni-list-rs/vsebina/" in s["url"] and status == 200:
        uradni_list(out, manifest, s["id"], s["url"], body)
    if "freight.scandlines.com/freight-conditions/" in s["url"] and status == 200:
        scandlines(out, manifest, s["id"], s["url"], body)
    if "unityline.eu/cargo/documents-polsca/" in s["url"] and status == 200:
        polsca(out, manifest, s["id"], s["url"], body)


def checked(s, status, body, again):
    """A source's answer once it holds what the source expects ("expect"; Overpass at
    times answers a query without the toll booths near the road): asked again,
    then an error, so the last run's copy is kept."""
    missing = lambda b: [x for x in s.get("expect", []) if x.encode() not in b]
    for wait in (60, 120, 240):
        if status != 200 or not missing(body):
            break
        time.sleep(wait)
        status, body = again()
    if status == 200 and missing(body):
        raise RuntimeError(f"the answer lacks {missing(body)}")
    return status, body


def overpass_all(items, out, manifest, errors):
    """The Overpass queries, on two threads that ask different instances first
    (overpass-api.de and overpass.private.coffee), so a busy one doesn't hold up
    the rest. A query no instance answers is asked again in a second round
    after a pause; three in a row unanswered mean Overpass is down, and the
    rest wait for that round too, which stops likewise (the last run's copies
    are kept)."""
    rounds, state, lock = [list(items), []], {"dead": 0}, threading.Lock()

    def worker(prefer, queue, later, last_round):
        while True:
            with lock:
                if not queue:
                    return
                s = queue.pop(0)
                down = state["dead"] >= 3
            if down:
                if last_round:
                    with LOCK:
                        errors.append(f"{s['id']}: Overpass is down (three queries in a row unanswered)")
                    print(f"ERROR {s['id']} Overpass is down", flush=True)
                else:
                    with lock:
                        later.append(s)
                continue
            try:
                status, body, asked = ask_overpass(s["url"], prefer)
                status, body = checked(s, status, body, lambda: ask_overpass(s["url"], prefer)[:2])
                with lock:
                    state["dead"] = 0
                store(out, manifest, s, status, body, asked)
            except Exception as e:
                with lock:
                    state["dead"] += 1
                    if not last_round:
                        later.append(s)
                if last_round:
                    with LOCK:
                        errors.append(f"{s['id']}: {e}")
                    print(f"ERROR {s['id']} {e}", flush=True)
                else:
                    print(f"refused, asked again later: {s['id']} {e}", flush=True)

    for n in (0, 1):
        queue, later = rounds[n], []
        if not queue:
            break
        if n:
            time.sleep(120)
            state["dead"] = 0
        threads = [threading.Thread(target=worker, args=(h, queue, later, n == 1)) for h in OVERPASS[:2]]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if n == 0:
            rounds[1] = later


def main(src, out):
    os.makedirs(out, exist_ok=True)
    manifest, errors = [], []
    sources = json.load(open(src, encoding="utf-8"))["sources"]
    # The Overpass queries run alongside the rest (overpass_all). The
    # Internet Archive's copies are fetched last, each asked once; the
    # archive refuses connections when asked too fast, so those it refused
    # are asked again after a pause, with retries. Five refusals in a row
    # mean it is down: the rest wait for the second round, which stops
    # likewise (the last run's copies are kept).
    osm = threading.Thread(target=overpass_all, args=([s for s in sources if "/api/interpreter" in s["url"]], out, manifest, errors))
    osm.start()
    sources = sorted((s for s in sources if "/api/interpreter" not in s["url"]), key=lambda s: "web.archive.org/" in s["url"])
    queue, later, refused = sources + [None], [], 0
    while queue:
        s = queue.pop(0)
        if s is None:
            if later:
                time.sleep(120)
                queue, later, refused = later, [], 0
            continue
        archive = "web.archive.org/" in s["url"]
        if archive and not s.get("again") and refused >= 5:
            later.append(dict(s, again=True))  # the archive seems down: asked after the pause
            continue
        if archive and s.get("again") and refused >= 5:
            with LOCK:
                errors.append(f"{s['id']}: the Internet Archive refused it (and five others in a row)")
            print(f"ERROR {s['id']} the Internet Archive keeps refusing", flush=True)
            continue
        try:
            accept = "application/json" if "nvdbapiles" in s["url"] else None
            if archive:
                status, body = get(s["url"], tries=3 if s.get("again") else 1, pause=20)
                refused = 0
            else:
                status, body = get(s["url"], accept)
            status, body = checked(s, status, body, lambda: get(s["url"], accept))
            # The Internet Archive's outage page instead of a capture: an
            # error, so the last run's copy is kept.
            if archive and b"Internet Archive services are temporarily offline" in body[:20000]:
                raise RuntimeError("the Internet Archive is temporarily offline")
            store(out, manifest, s, status, body, s["url"])
        except Exception as e:
            if archive:
                refused += 1
            if archive and not s.get("again"):
                print(f"refused, asked again later: {s['id']} {e}", flush=True)
                later.append(dict(s, again=True))
                continue
            with LOCK:
                errors.append(f"{s['id']}: {e}")
            print(f"ERROR {s['id']} {e}", flush=True)
    osm.join()
    manifest.sort(key=lambda f: f.get("file", ""))
    json.dump({"files": manifest, "errors": sorted(errors)}, open(os.path.join(out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
