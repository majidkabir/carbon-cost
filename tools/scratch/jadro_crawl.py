import re, sys, json, time, urllib.request, urllib.parse, html, os
UA = {"User-Agent": "Mozilla/5.0"}
def get(u, binary=False):
    for i in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u, safe=":/?=&%"), headers=UA), timeout=60).read()
            return b if binary else b.decode("utf-8", "replace")
        except Exception as e:
            print("retry", u, e); time.sleep(5)
    return b"" if binary else ""
h = get("https://www.jadrolinija.hr/hr/putovanja/lokalne_linije")
lines = sorted(set(re.findall(r'href="(https://www\.jadrolinija\.hr/hr/putovanje/[^"]+)"', h)))
out = []
os.makedirs("out/lines", exist_ok=True)
lines = [u for u in lines if "–" in u or "split_–_vis" in u]
for u in lines:
    p = get(u)
    slug = u.rsplit("/", 1)[-1]
    open(f"out/lines/{slug[:80]}.html", "w").write(p)
    t = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", p)
    links = [(m.group(1), re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()) for m in re.finditer(r'<a[^>]+href="([^"]*download/[0-9a-f]{32}[^"]*)"[^>]*>([\s\S]{0,400}?)</a>', p)]
    out.append({"url": u, "title": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t.group(1)))).strip() if t else "", "links": links})
    print(u, out[-1]["title"], links)
    for k, (l, txt) in enumerate(links):
        b = get(l if l.startswith("http") else "https://www.jadrolinija.hr" + l, binary=True)
        open(f"out/lines/{slug[:60]}-{k}.pdf", "wb").write(b)
json.dump(out, open("out/jadro-lines.json", "w"), ensure_ascii=False, indent=1)
