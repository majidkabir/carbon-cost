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

# What /v1/factors holds besides vehicle types: its shape, and any factors
# per litre of fuel or per kWh of electricity (for primary energy data).
st, body = get("/v1/factors")
if st == 200:
    try:
        f = json.loads(body)
    except ValueError:
        f = None
    def shape(x, depth=0):
        if isinstance(x, dict):
            return "{" + ", ".join(f"{k}: {shape(v, depth + 1) if depth < 2 else type(v).__name__}" for k, v in list(x.items())[:12]) + (", …" if len(x) > 12 else "") + "}"
        if isinstance(x, list):
            return f"[{len(x)} × {shape(x[0], depth + 1) if x and depth < 3 else ''}]"
        return type(x).__name__
    print("factors shape:", shape(f)[:3000])
    for word in ["per_l", "litre", "liter", "per_kwh", "kwh", "grid", "electricity_mix", "energy_carrier", "fuel"]:
        hits = [m.start() for m in re.finditer(word, body)]
        print(f"'{word}': {len(hits)} hits" + (f"; e.g. …{body[max(0, hits[0] - 300):hits[0] + 300]}…" if hits else ""))

# The fuel factors for primary data: aliases, regions, and the diesel and
# electricity entries.
if st == 200 and isinstance(f, dict):
    print("note:", f.get("note"))
    print("fuel_aliases:", json.dumps(f.get("fuel_aliases")))
    print("fuel_regions:", json.dumps(f.get("fuel_regions"))[:3000])
    fu = f.get("fuels") or []
    units = sorted({x.get("unit") for x in fu})
    print("fuel units:", units, "fuels:", len(fu))
    for x in fu:
        if re.search(r"diesel|electric|hvo", x.get("fuel", ""), re.I) and (x.get("unit") in ("l", "litre", "kWh", "kwh") or True):
            print("fuel:", json.dumps(x)[:400])

# Primary energy for an electric truck: Sootcase's note says to give
# energy_kwh_per_tkm with the country. Which leg fields does it take?
def calc_leg(extra):
    leg = {"id": "road", "mode": "road", "vehicle_type": "glec/road/europe/electric/artic_34_40t",
           "from": {"lat": 54.3233, "lon": 10.1228}, "to": {"lat": 53.5511, "lon": 9.9937}, **extra}
    body = json.dumps({"id": "t", "weight_kg": 20000, "add_road_legs": False, "legs": [leg]}).encode()
    req = urllib.request.Request(BASE + "/v1/calculate", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)
            l = res["legs"][0]
            return f"200 wtw {res.get('wtw_kg')} ttw {res.get('ttw_kg')}; leg keys {sorted(l)}; parts {json.dumps(l.get('parts'))[:300]}"
    except urllib.error.HTTPError as e:
        return f"{e.code} {e.read().decode('utf-8', 'replace')[:400]}"
for extra in [{}, {"energy_kwh_per_tkm": 0.06}, {"energy_kwh_per_tkm": 0.06, "country": "DE"}, {"energy_kwh_per_tkm": 0.06, "country": "NO"},
              {"energy_kwh_per_tkm": 0.06, "energy_country": "NO"}, {"energy_kwh": 120, "country": "NO"}, {"fuel_l": 30}, {"no_such_field": 1}]:
    print("leg", json.dumps(extra), "->", calc_leg(extra))

# Where the grid factors are: every top-level key of /v1/factors, and the
# entries naming DNK or a grid.
if st == 200 and isinstance(f, dict):
    print("factor keys:", sorted(f))
    for k, v in f.items():
        txt = json.dumps(v)
        if re.search(r"\bDNK\b|grid", txt):
            print(f"key {k}: {txt[:1500]}")
for extra in [{"energy_kwh_per_tkm": 0.06, "country": "DNK"}, {"energy_kwh_per_tkm": 0.06, "country": "NOR"}, {"energy_kwh_per_tkm": 0.06, "country": "DEU"}]:
    print("leg", json.dumps(extra), "->", calc_leg(extra))
