"""Scratch: asks the toll endpoint of Autostrade per l'Italia's traffic
site (its station-to-station toll form) for a few pairs."""
import json, os, sys, time, urllib.request

UA = {"User-Agent": "carbon-cost tables fetch (github.com/majidkabir/carbon-cost)", "Accept-Language": "it,en",
      "Content-Type": "application/json", "Accept": "application/json"}
URL = "https://d27zlgkawwz6vy.cloudfront.net/sitoaspi-prod/tolling/"
PAIRS = [(13, 20, 1), (401, 408, 1), ("997", 191, 24), ("997", 1, 8), ("997", 3, 8), ("997", 417, 9)]
out = sys.argv[1]
for a, b, ret in PAIRS:
    body = json.dumps({"cStzIni": a, "cStzFin": b, "cRet": ret}).encode()
    req = urllib.request.Request(URL, data=body, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, resp = r.status, r.read()
    except Exception as e:
        status, resp = getattr(e, "code", 0), (e.read() if hasattr(e, "read") else str(e).encode())
    open(os.path.join(out, f"aspi-toll-{a}-{b}-{ret}.json"), "wb").write(resp)
    print(a, b, ret, status, resp[:400])
    time.sleep(2)
