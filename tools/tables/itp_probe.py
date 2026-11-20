"""Scratch: asks Ivrea Torino Piacenza's toll calculator (its A21 page's
form) for a few entry/exit pairs and prints the answers."""
import json, re, time, urllib.parse, urllib.request, html

UA = {"User-Agent": "carbon-cost tables fetch (github.com/majidkabir/carbon-cost)", "Accept-Language": "en"}
URL = "https://www.itpspa.it/wp-admin/admin-ajax.php"
PAIRS = [("445", "447"), ("447", "448"), ("445", "449"), ("447", "449")]
for a, b in PAIRS:
    body = urllib.parse.urlencode({"action": "calcola_pedaggio", "entrata": a, "uscita": b, "classe": "", "show_classe": "0", "lang": "en"}).encode()
    req = urllib.request.Request(URL, data=body, headers={**UA, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                                          "X-Requested-With": "XMLHttpRequest", "Referer": "https://www.itpspa.it/en/section-a21/toll-info/"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", d["data"]))) if d.get("success") else d.get("data")
    except Exception as e:
        txt = str(e)
    print("PAIR", a, b, txt)
    time.sleep(3)
