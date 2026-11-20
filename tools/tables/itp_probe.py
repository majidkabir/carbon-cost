"""Scratch: asks Ivrea Torino Piacenza's toll calculator (its A5 page's
form) for a few entry/exit pairs and saves the answers."""
import json, os, re, sys, time, urllib.parse, urllib.request, html

UA = {"User-Agent": "carbon-cost tables fetch (github.com/majidkabir/carbon-cost)", "Accept-Language": "en"}
URL = "https://www.itpspa.it/wp-admin/admin-ajax.php"
PAIRS = [("401", "408"), ("400", "408"), ("402", "408"), ("403", "408"), ("401", "402"), ("400", "402"), ("402", "403"), ("401", "400")]
out = sys.argv[1]
for a, b in PAIRS:
    body = urllib.parse.urlencode({"action": "calcola_pedaggio", "entrata": a, "uscita": b, "classe": "", "show_classe": "0", "lang": "en"}).encode()
    req = urllib.request.Request(URL, data=body, headers={**UA, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                                          "X-Requested-With": "XMLHttpRequest", "Referer": "https://www.itpspa.it/en/?p=8466"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = r.read()
        d = json.loads(resp)
        txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", d["data"]))) if d.get("success") else d.get("data")
    except Exception as e:
        txt = str(e)
    print("PAIR", a, b, txt)
    time.sleep(3)
