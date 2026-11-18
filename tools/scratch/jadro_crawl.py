import re, sys, json, time, urllib.request, html
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8", "replace")
        except Exception as e:
            print("retry", u, e); time.sleep(5)
    return ""
seen, out = set(), []
start = ["https://www.jadrolinija.hr/hr/putovanja", "https://www.jadrolinija.hr/hr/putovanja/lokalne-linije", "https://www.jadrolinija.hr/hr/obavijesti-za-putnike"]
queue = list(start)
pages = {}
while queue and len(seen) < 150:
    u = queue.pop(0)
    if u in seen: continue
    seen.add(u)
    h = get(u)
    pages[u] = h
    for m in re.finditer(r'href="(https://www\.jadrolinija\.hr/hr/putovanja[^"#?]*)"', h):
        if m.group(1) not in seen: queue.append(m.group(1))
    for m in re.finditer(r'<a[^>]+href="([^"]*download/[0-9a-f]{32})"[^>]*>([\s\S]{0,300}?)</a>', h):
        out.append({"page": u, "url": m.group(1), "text": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()})
    t = re.search(r"<title>([\s\S]*?)</title>", h)
    print(u, len(h), t.group(1).strip()[:80] if t else "")
json.dump(out, open("out/jadro-links.json", "w"), ensure_ascii=False, indent=1)
for u, h in pages.items():
    open("out/jadro-" + re.sub(r"[^a-z_]", "-", u.split("/hr/")[-1])[:60] + ".html", "w").write(h)
print(len(out), "download links")
