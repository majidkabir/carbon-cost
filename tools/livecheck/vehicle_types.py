"""Asks a local Sootcase which road vehicle types it knows, as a black box:
its OpenAPI document and vehicle-type endpoints where it has them, and a
calculation with each candidate electric truck type. Prints what it found.

Usage: python3 vehicle_types.py http://localhost:8080
"""
import json, re, sys, urllib.request, urllib.error

BASE = sys.argv[1]


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def calc(vt):
    leg = {"id": "road", "mode": "road", "vehicle_type": vt, "from": {"lat": 54.3233, "lon": 10.1228}, "to": {"lat": 53.5511, "lon": 9.9937}}
    body = json.dumps({"id": "t", "weight_kg": 20000, "add_road_legs": False, "legs": [leg]}).encode()
    req = urllib.request.Request(BASE + "/v1/calculate", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:600]


types = set()
for path in ["/openapi.json", "/v1/openapi.json", "/v1/vehicle-types", "/v1/vehicle_types", "/v1/vehicles", "/v1/factors", "/v1/datasets"]:
    st, body = get(path)
    found = set(re.findall(r"glec/road/[a-z0-9_/.-]+", body))
    types |= found
    print(f"GET {path}: {st}, {len(body)} bytes, {len(found)} road types" + (f"; starts {body[:200]!r}" if st == 200 and not found else ""))
road = sorted(types)
print("road vehicle types seen:", json.dumps(road))
cands = [t for t in road if re.search(r"bev|electric|battery", t)] or [
    "glec/road/eu_sa/artic_34_40t/bev", "glec/road/eu_sa/artic_34_40t/battery_electric", "glec/road/eu_sa/artic_34_40t/electric"]
for vt in cands[:8]:
    st, res = calc(vt)
    if st == 200:
        leg = res["legs"][0]
        print(f"POST calculate {vt}: 200, ttw {res.get('ttw_kg')} wtw {res.get('wtw_kg')} kg, intensity {res.get('intensity_g_per_tkm')} g/tkm, {leg.get('distance_km')} km")
    else:
        print(f"POST calculate {vt}: {st} {res}")
st, res = calc("glec/road/eu_sa/artic_34_40t/diesel")
print("diesel for comparison:", st, res.get("ttw_kg") if isinstance(res, dict) else res, res.get("wtw_kg") if isinstance(res, dict) else "")
