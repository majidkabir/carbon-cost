"""Checks Sootcase's country sections (docs/requirements/sootcase-country-sections.md)
and what its results say about Regulation (EU) 2026/1030
(docs/requirements/sootcase-count-emissions.md) against a local Sootcase
on the Denmark, Schleswig-Holstein and Hamburg extracts, as a black box:
only its API answers.

Usage: python3 sections.py http://localhost:8080

Prints PASS, FAIL or SKIP for each check with what it saw, and exits 1 on
any FAIL.
"""
import json, sys, urllib.request, urllib.error

BASE = sys.argv[1]
results = []


def say(check, verdict, what):
    results.append(verdict)
    print(f"{verdict} {check}: {what}", flush=True)


def calc(frm, to, query="country_km=true", ferries=True):
    leg = {"id": "road", "mode": "road", "vehicle_type": "glec/road/eu_sa/artic_34_40t/diesel",
           "from": {"lat": frm[0], "lon": frm[1]}, "to": {"lat": to[0], "lon": to[1]}}
    if not ferries:
        query += "&avoid=ferries"
    body = json.dumps({"id": "trip", "weight_kg": 20000, "add_road_legs": False, "legs": [leg]}).encode()
    req = urllib.request.Request(f"{BASE}/v1/calculate?{query}", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def leg0(res):
    legs = res.get("legs") or []
    return legs[0] if legs else {}


def contiguous(parts, start, end, key):
    """The parts run from start to end, each from where the last ended."""
    at = start
    for p in parts:
        if abs(p.get("from_km", -1) - at) > 0.05:
            return f"{key} starts at {p.get('from_km')} where {at} was expected"
        at = p.get("to_km", -1)
    if abs(at - end) > 0.05:
        return f"{key} ends at {at}, not {end}"
    return ""


def check_sections(name, leg, want_countries, want_regions=None):
    secs = leg.get("country_sections")
    if not secs:
        say(name, "FAIL", f"no country_sections (keys: {sorted(leg)})")
        return
    countries = [s.get("country") for s in secs if not s.get("ferry")]
    order = [c for i, c in enumerate(countries) if i == 0 or c != countries[i - 1]]
    problems = []
    if order != want_countries:
        problems.append(f"countries {order}, want {want_countries}")
    if err := contiguous(secs, 0, leg.get("distance_km", 0), "sections"):
        problems.append(err)
    for cc, km in (leg.get("country_km") or {}).items():
        got = sum(s["to_km"] - s["from_km"] for s in secs if s.get("country") == cc and not s.get("ferry"))
        if abs(got - km) > 0.05:
            problems.append(f"{cc} sections {got:.2f} km, country_km {km:.2f}")
    if want_regions is not None:
        regs = [r.get("region") for s in secs for r in (s.get("regions") or [])]
        rorder = [r for i, r in enumerate(regs) if i == 0 or r != regs[i - 1]]
        if rorder != want_regions:
            problems.append(f"regions {rorder}, want {want_regions}")
        for s in secs:
            if s.get("regions") and (err := contiguous(s["regions"], s["from_km"], s["to_km"], f"{s['country']} regions")):
                problems.append(err)
    ferries = [s for s in secs if s.get("ferry")]
    seen = ", ".join(f"{s.get('country') or 'ferry'} {s['from_km']:.1f}-{s['to_km']:.1f}" + (" (ferry)" if s.get("ferry") else "")
                     + (" [" + ", ".join(f"{r.get('region')} {r['from_km']:.1f}-{r['to_km']:.1f}" for r in s["regions"]) + "]" if s.get("regions") else "") for s in secs)
    say(name, "FAIL" if problems else "PASS", ("; ".join(problems) + " | " if problems else "") + seen + (f"; {len(ferries)} ferry section(s)" if ferries else ""))


def check_basis(name, res):
    text = json.dumps(res).lower()
    basis = res.get("basis") or {}
    cert = res.get("certification") or ""
    problems = []
    if "14083" not in json.dumps(basis):
        problems.append(f"basis {basis!r} names no EN ISO 14083")
    if not basis.get("sootcase") and not basis.get("version"):
        problems.append("basis has no Sootcase version")
    if "not certified" not in cert.lower() or "2026/1030" not in cert:
        problems.append(f"certification {cert!r}")
    if "in accordance with regulation" in text:
        problems.append("the Art. 10 line is in the response")
    if problems:
        # What the response has instead, to tell a missing field from a renamed one.
        hits = {k: v for k, v in res.items() if any(w in k.lower() for w in ("basis", "cert", "standard", "method", "version", "framework", "regulation"))}
        problems.append(f"top-level keys {sorted(res)}; related {json.dumps(hits)[:400]}")
        found = [m.start() for m in __import__("re").finditer("14083|glec|2026/1030", text)]
        problems.append(f"14083/GLEC/2026-1030 mentioned at {len(found)} places" + (f", e.g. …{text[max(0, found[0] - 80):found[0] + 80]}…" if found else ""))
    say(name, "FAIL" if problems else "PASS", "; ".join(problems) or f"basis {basis}, certification {cert!r}")


def main():
    # Kolding (DK) to Hamburg: Denmark, then Schleswig-Holstein and Hamburg.
    st, res = calc((55.4904, 9.4722), (53.5511, 9.9937), ferries=False)
    if st != 200:
        say("C1 Kolding-Hamburg", "FAIL", f"HTTP {st}: {str(res)[:200]}")
    else:
        check_sections("C1 Kolding-Hamburg", leg0(res), ["DK", "DE"], ["DE-SH", "DE-HH"])
        check_basis("E1 basis and certification", res)
        st2, res2 = calc((55.4904, 9.4722), (53.5511, 9.9937), query="country_km=true&path=full", ferries=False)
        same = st2 == 200 and leg0(res2).get("country_sections") == leg0(res).get("country_sections")
        say("R3 same with path=full", "PASS" if same else "FAIL", "" if same else f"HTTP {st2}")
        # The primary's main roads, without alternatives asked for (for
        # matching bans on listed roads to the route).
        roads = (leg0(res).get("summary") or {}).get("roads")
        say("S1 summary roads on the primary", "PASS" if roads else "FAIL", f"roads {roads}")
    # Copenhagen to Hamburg via Rødby-Puttgarden: a ferry section between.
    st, res = calc((55.6761, 12.5683), (53.5511, 9.9937))
    if st != 200:
        say("C1 Copenhagen-Hamburg", "FAIL", f"HTTP {st}: {str(res)[:200]}")
    else:
        leg = leg0(res)
        check_sections("C1 Copenhagen-Hamburg", leg, ["DK", "DE"])
        if not any(s.get("ferry") for s in leg.get("country_sections") or []):
            print("note: no ferry section (the route may have gone by land)")
    # Within Germany: Kiel to Hamburg, one country, two states.
    st, res = calc((54.3233, 10.1228), (53.5511, 9.9937))
    if st != 200:
        say("C3 Kiel-Hamburg", "FAIL", f"HTTP {st}: {str(res)[:200]}")
    else:
        check_sections("C3 Kiel-Hamburg", leg0(res), ["DE"], ["DE-SH", "DE-HH"])
    print(f"{results.count('PASS')} pass, {results.count('FAIL')} fail, {results.count('SKIP')} skip")
    sys.exit(1 if "FAIL" in results else 0)


main()
