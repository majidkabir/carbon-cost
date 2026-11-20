"""Scratch: asks Ivrea Torino Piacenza's toll calculator (its A5 page's
form) for a few entry/exit pairs and saves the answers."""
import json, os, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "carbon-cost tables fetch (github.com/majidkabir/carbon-cost)", "Accept-Language": "en"}
URL = "https://www.itpspa.it/wp-admin/admin-ajax.php"
PAIRS = [("401", "408"), ("408", "401"), ("401", "1"), ("997", "998"), ("998", "997"), ("400", "997")]
out = sys.argv[1]
for a, b in PAIRS:
    body = urllib.parse.urlencode({"action": "calcola_pedaggio", "entrata": a, "uscita": b, "classe": "", "show_classe": "0", "lang": "en"}).encode()
    req = urllib.request.Request(URL, data=body, headers={**UA, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                                          "X-Requested-With": "XMLHttpRequest", "Referer": "https://www.itpspa.it/en/?p=8466"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, resp = r.status, r.read()
    except Exception as e:
        status, resp = getattr(e, "code", 0), (e.read() if hasattr(e, "read") else str(e).encode())
    open(os.path.join(out, f"itp-{a}-{b}.json"), "wb").write(resp)
    print(a, b, status, resp[:300])
    time.sleep(3)
