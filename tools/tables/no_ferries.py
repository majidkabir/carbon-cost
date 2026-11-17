"""Builds Norway's national road ferries (riksvegferjer) as toll systems
(no-ferries-<date>.json): the fare per crossing by vehicle length, from

- the AutoPASS-regulativ for ferjetakster's price table (Statens vegvesen,
  no-ferje-autopass-pris.txt): the full price by zone and length group
  AP1-AP9, VAT (12%) included;
- the regulativ itself (no-ferje-autopass-reg.txt): the vehicle is priced
  by its total length with trailer and load; business customers with a
  prepaid AutoPASS ferry account get 40% off;
- the Minister of Transport's answer to the Storting of 11 December 2025
  (no-stortinget-699.txt, written question 699): each national road ferry
  route's zone, by stretch, and its full AP1 price then (2025), which must
  agree with the 2026 table less its 3.6% rise; stretches priced 0 there
  are free;
- the national road database NVDB (no-nvdb-770.json, Ferjesamband, and
  no-nvdb-64.json, Ferjekai): each route's quays and where they are.

Moss-Horten has a regulativ of its own and isn't built; the toll
(bompenger) charged on board Mortavika-Arsvågen isn't included.

Usage: python3 no_ferries.py <fetched dir> <out dir>
"""
import glob
import json
import os
import re
import sys

LENGTHS = [("AP1", None, 6.0), ("AP2", 6.0, 8.0), ("AP3", 8.0, 10.0), ("AP4", 10.0, 12.5), ("AP5", 12.5, 14.5),
           ("AP6", 14.5, 17.5), ("AP7", 17.5, 19.5), ("AP8", 19.5, 22.0), ("AP9", 22.0, None)]
HEADER = "<6m 6,01-8m 8,01-10m 10,01-12,5m 12,51-14,5m 14,51-17,5m 17,51-19,5m 19,51-22m >22m"
MONTHS = {m: i + 1 for i, m in enumerate(("januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"))}
URLS = {"price": "https://www.vegvesen.no/globalassets/fag/trafikk/ferje/pris---autopass-regulativ---fullpris---01.01.2026.pdf",
        "rules": "https://www.vegvesen.no/globalassets/fag/trafikk/ferje/autopass-reg.-for-ferje-fra-01.01.2026.pdf",
        "answer": "https://www.stortinget.no/globalassets/pdf/dokumentserien/2025-2026/dok15-202526-0699-vedlegg.pdf"}


def flat(path):
    return re.sub(r"\s+", " ", open(path, encoding="utf-8", errors="replace").read())


def key(name):
    return re.sub(r"\s+", "", name.lower().replace("–", "-"))


def objects(fetched, sid):
    """The NVDB objects of a fetched query, over its pages (<sid>.json, <sid>-2.json, ...)."""
    out = []
    for p in [os.path.join(fetched, f"{sid}.json")] + sorted(glob.glob(os.path.join(fetched, f"{sid}-[0-9]*.json")), key=lambda p: int(re.search(r"-(\d+)\.json$", p).group(1))):
        out += json.load(open(p)).get("objekter") or []
    return out


def prop(o, name):
    return next((e.get("verdi") for e in o.get("egenskaper", []) if e.get("navn") == name), None)


def where(o):
    """A quay's place: the middle of its NVDB geometry (WKT, latitude first in srid 4326)."""
    wkt = (o.get("geometri") or {}).get("wkt", "")
    pts = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+\.\d+) (-?\d+\.\d+)", wkt)]
    if not pts:
        return None
    return round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)


def main(fetched, out):
    try:
        price = open(os.path.join(fetched, "no-ferje-autopass-pris.txt"), encoding="utf-8").read()
        rules = flat(os.path.join(fetched, "no-ferje-autopass-reg.txt"))
        answer = open(os.path.join(fetched, "no-stortinget-699.txt"), encoding="utf-8").read()
        routes, quays = objects(fetched, "no-nvdb-770"), {o["id"]: o for o in objects(fetched, "no-nvdb-64")}
    except (OSError, ValueError):
        print("Norwegian ferries: a source wasn't fetched; not built")
        return
    # The price table: the date, the length groups, a row per zone.
    day = re.search(r"Inkl\. 12 % mva, gjeldende f\.o\.m\. (\d{1,2})\. (\w+) (\d{4})", price)
    if not day or HEADER not in re.sub(r"\s+", " ", price) or day.group(2) not in MONTHS:
        sys.exit("Norwegian ferries: the price table's date or length groups not read")
    start = f"{day.group(3)}-{MONTHS[day.group(2)]:02d}-{int(day.group(1)):02d}"
    zones = {}
    for ln in price.splitlines():
        m = re.match(r"^\s*(\d+)\s+((?:\d+\s+){9})(\d+)\s*$", ln)
        if m:
            zones[int(m.group(1))] = [int(x) for x in m.group(2).split()]
    if sorted(zones)[:2] != [0, 1] or len(zones) < 100:
        sys.exit(f"Norwegian ferries: the price table's zones not read ({len(zones)})")
    # The rules: priced by total length with trailer and load; 40% off with a business account.
    for needle in ("Kjøretøy takstberegnes etter kjøretøyets målte totallengde", "Kjøretøy over 6 meter og med tilhenger takseres som ett kjøretøy",
                   "Bedriftskunder kan oppnå 40 % rabatt"):
        if needle not in rules:
            sys.exit(f"Norwegian ferries: the regulativ no longer says {needle!r}")
    # The Minister's answer: zone and 2025 AP1 full price by stretch.
    stretches = {}
    for ln in answer.splitlines():
        m = re.match(r"^\s*(\S.*?[a-zæøå])\s{2,}(\S.*?[a-zæøå])\s{2,}(\d+)\s+(\d+)(\*?)\s*$", ln)
        if m:
            stretches.setdefault(m.group(1), []).append((m.group(2), int(m.group(3)), int(m.group(4)), bool(m.group(5))))
    toll_note = re.search(r"\* Taksten er inklusive (\d+) kr i bompengar", answer)
    if len(stretches) < 14:
        sys.exit(f"Norwegian ferries: the Minister's table not read ({len(stretches)} routes)")
    systems, notes = [], []
    by_name = {key(prop(o, "Navn") or ""): o for o in routes if "Riks" in str(prop(o, "Sambandstype"))}
    for route, rows in stretches.items():
        o = by_name.get(key(route.replace("–", "-")))
        if not o:
            # NVDB names a multi-stop route by its stops in another order.
            o = next((v for k, v in by_name.items() if sorted(k.split("-")) == sorted(key(route).split("-"))), None)
        if not o:
            sys.exit(f"Norwegian ferries: {route} isn't a national road ferry route in NVDB")
        ids = [i for b in (o.get("relasjoner") or {}).get("barn", []) if b.get("type", {}).get("id") == 64 for i in b["vegobjekter"]]
        qs = {}
        for i in ids:
            q = quays.get(i)
            if q and where(q):
                qs[re.sub(r"\s+(ferjekai|kai)$", "", prop(q, "Navn") or "", flags=re.I)] = where(q)
        stations, prices = {}, {}
        for stretch, zone, ap1_2025, toll in rows:
            ends = stretch.split("–")
            found = []
            for e in ends:
                hit = [n for n in qs if n.lower().startswith(e.strip().lower())]
                found.append(hit[0] if len(hit) == 1 else None)
            if found.count(None) == 1 and len(qs) == 2:
                found[found.index(None)] = next(n for n in qs if n not in found)
            if None in found:
                sys.exit(f"Norwegian ferries: {route}: {stretch}'s quays not found among {sorted(qs)}")
            if zone not in zones:
                sys.exit(f"Norwegian ferries: {route}: zone {zone} isn't in the price table")
            free = ap1_2025 == 0
            if not free:
                # The 2025 AP1 price (less the on-board toll) is the 2026 one less its 3.6% rise.
                ferry_2025 = ap1_2025 - (int(toll_note.group(1)) if toll and toll_note else 0)
                if abs(zones[zone][0] / 1.036 - ferry_2025) > 3:
                    sys.exit(f"Norwegian ferries: {route} {stretch}: zone {zone}'s AP1 {zones[zone][0]} doesn't follow from {ferry_2025} in 2025")
            if toll:
                notes.append(f"{stretch}: the toll (bompenger) charged on board isn't included")
            for e in found:
                stations[e] = qs[e]
            p = {g: (0 if free else zones[zone][k]) for k, (g, _, _) in enumerate(LENGTHS)}
            prices[f"{found[0]}|{found[1]}"] = p
            if free:
                notes.append(f"{stretch} is free (priced 0 in the Minister's table)")
        groups = []
        for g, lo, hi in LENGTHS:
            gg = {"name": g}
            if lo:
                gg["min_length_m"] = lo
            if hi:
                gg["max_length_m"] = hi
            groups.append(gg)
        systems.append({"name": f"{route} ferry", "law": f"AutoPASS-regulativ for ferjetakster: {route}, by stretch (zone)", "groups": groups,
                        "stations": [{"name": n, "points": [{"name": f"{n} ferry quay", "lat": a, "lon": b}]} for n, (a, b) in sorted(stations.items())],
                        "prices": prices, "discounts": [{"name": "AutoPASS ferry account, business, prepaid (40%)", "etc": True, "percent": 40}]})
        print(route, {k: v["AP6"] for k, v in prices.items()})
    t = {"country": "NO", "currency": "NOK", "valid_from": start, "crossings": True,
         "name": "Norwegian national road ferries (riksvegferjer)",
         "law": (f"AutoPASS-regulativ for ferjetakster from {start} (Statens vegvesen, set by the Ministry of Transport): the full price per crossing by zone and the vehicle's "
                 "total length with trailer and load (AP1 up to 6 m ... AP6 14.51-17.5 m, AP7 17.51-19.5 m, AP8 19.51-22 m, AP9 over 22 m), VAT (12%) included; "
                 "`etc` the prepaid business account's 40% discount. Each national road ferry route's zone by stretch from the Minister of Transport's answer to the Storting "
                 "of 11 December 2025 (written question 699), checked against the table; the quays from NVDB. Moss-Horten (a regulativ of its own) isn't priced. "
                 + " ".join(f"{n}." for n in notes)),
         "sources": [{"title": "Statens vegvesen: AutoPASS-regulativ for ferjetakster, takster (fullpris) fra 1. januar 2026", "url": URLS["price"]},
                     {"title": "Statens vegvesen: AutoPASS-regulativ for ferjetakster fra 1. januar 2026", "url": URLS["rules"]},
                     {"title": "Samferdselsministeren: svar på skriftleg spørsmål nr. 699 (2025-2026), billettpris og takstsone for riksvegferjesambanda", "url": URLS["answer"]},
                     {"title": "NVDB (Statens vegvesen): Ferjesamband (770) and Ferjekai (64)", "url": "https://nvdbapiles.atlas.vegvesen.no/vegobjekter/api/v4/vegobjekter/770"}],
         "vehicles": "Any vehicle, by total length with trailer and load (give truck.length_m; 16.5 m assumed)",
         "tolled_roads": "Norway's national road ferry routes (riksvegferjesamband) priced by the AutoPASS-regulativ, from quay to quay.",
         "closed_systems": systems, "rows": []}
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"no-ferries-{start}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(systems), "routes")


if __name__ == "__main__":
    main(*sys.argv[1:])
