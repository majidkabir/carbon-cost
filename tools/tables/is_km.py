"""Builds Iceland's kílómetragjald tables (is-<valid_from>.json) from Lög um
kílómetragjald á ökutæki nr. 100/2025 in Alþingi's lagasafn (fetched as
is-althingi-100-2025.html, the Internet Archive's copy: althingi.is refuses
the workflow).

The law charges every vehicle per km of its odometer, the motor vehicle and
the trailer each by its own gjaldþyngd (6. gr.: the permissible total weight
on registration, for 10,000 kg or more at most the annex's maximum by axles).
The tables give each vehicle its own rows (vehicle_unit "motor" and
"trailer"): the 6. gr. band for its mass, capped by its axles. The
temporary provisions set the trailer at 60 % of its band in 2026 (and charge
only trailers of 10,000 kg or more, those of 7. gr. 2. mgr.) and 80 % in
2027 (VI.4, VII), and trucks of 10,000 kg or more running on methane,
methanol, electricity or hydrogen, with their trailers, at 20 % from 2026 to
2029 (VI.5; ORCT energy cng, lng, electric or hydrogen). Buses' discounts
(VI.1-3) are left out: carbon-cost prices trucks.

Usage: python3 is_km.py <fetched dir> <out dir>
"""
import html
import json
import os
import re
import sys

SOURCE = "https://www.althingi.is/lagas/nuna/2025100.html"
CLEAN = ["cng", "lng", "electric", "hydrogen"]


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def kg(s):
    return int(s.replace(".", ""))


def kr(s):
    return float(s.replace(",", "."))


def read(t):
    """The law's amounts: the 6. gr. bands, the annex's maxima, the
    temporary provisions' percentages."""
    v = re.search(r"Íslensk lög (\d+\. \S+ \d{4})\. Útgáfa (\w+)\.", t)
    a = t.find("6. gr. Fjárhæð kílómetragjalds.")
    b = t.find("Fjárhæð kílómetragjalds af ökutæki sem fellur undir 1. mgr. 3. gr. ræðst af gjaldþyngd þess.", a)
    if not v or a < 0 or b < 0:
        sys.exit("Lög nr. 100/2025: 6. gr. not found")
    table = t[a:b]
    bands = [(kg(lo), kg(hi), kr(r)) for lo, hi, r in re.findall(r"\b(0|\d{1,2}\.\d{3})–(\d{1,2}\.\d{3}) (\d+,\d\d)\b", table)]
    top = re.search(r"(\d{1,2}\.\d{3}) og yfir (\d+,\d\d)", table)
    if not top:
        sys.exit("Lög nr. 100/2025: the top band of 6. gr. not found")
    bands = sorted(bands) + [(kg(top.group(1)), None, kr(top.group(2)))]
    for (lo, hi, _), (lo2, _, _) in zip(bands, bands[1:]):
        if lo2 != hi + 1:
            sys.exit(f"Lög nr. 100/2025: 6. gr. bands not contiguous at {hi}")
    if bands[0][0] != 0 or len(bands) != 29:
        sys.exit(f"Lög nr. 100/2025: 6. gr. has {len(bands)} bands, not 29")
    cap_rule = re.search(r"Gjaldþyngd ökutækis sem er (\d{1,2}\.\d{3}) kg að leyfðri heildarþyngd eða meira skal þó að hámarki vera sú gjaldþyngd sem fram kemur í viðauka", t[b:b + 600])
    ann = t[t.find("Viðauki. Hámark gjaldþyngdar."):]
    caps = {}
    for key, pat in (("motor", r"1\.1 Tvíása bifreið (\S+) 1\.2 Þríása bifreið (\S+) 1\.3 Fjórása bifreið eða meira (\S+)"),
                     ("trailer", r"2\.1 Einása eftirvagn (\S+) 2\.2 Tvíása eftirvagn (\S+) 2\.3 Þríása eftirvagn eða meira (\S+)")):
        m = re.search(pat, ann)
        if not m:
            sys.exit(f"Lög nr. 100/2025: the annex's {key} maxima not found")
        caps[key] = [kg(x) for x in m.groups()]
    vi4 = re.search(r"4\. Fjárhæð gjalds á hvern ekinn kílómetra eftirvagns skal vera (\d+)% af fjárhæð gjaldflokks hlutaðeigandi eftirvagns "
                    r"á árinu (\d{4}) og (\d+)% af fjárhæð gjaldflokks hlutaðeigandi eftirvagns á árinu (\d{4})\.", t)
    vi5 = re.search(r"sem knúin er metani, metanóli, rafmagni eða vetni og er (\d{1,2}\.\d{3}) kg eða meira að leyfðri heildarþyngd, "
                    r"þ\.m\.t\. slíks samtengds ökutækis, þ\.e\. vagnlestar, skal vera (\d+)% af fjárhæð gjaldflokks hlutaðeigandi bifreiðar, "
                    r"eða eftir atvikum samtengds ökutækis, á árunum (\d{4}), (\d{4}), (\d{4}) og (\d{4})\.", t)
    vii = re.search(r"VII\. Þrátt fyrir 4\. tölul\. 1\. mgr\. 3\. gr\. skal gjaldskylda eftirvagna á árinu (\d{4}) eingöngu miðuð við þá eftirvagna sem falla undir 2\. mgr\. 7\. gr\.", t)
    seven = re.search(r"Þrátt fyrir 1\. mgr\. skal að lágmarki á sex mánaða fresti skrá stöðu akstursmælis, þ\.m\.t\. ökurita gjaldskylds ökutækis skv\. 1\. mgr\. 3\. gr\. sem er (\d{1,2}\.\d{3}) kg eða meira", t)
    if not (cap_rule and vi4 and vi5 and vii and seven):
        sys.exit("Lög nr. 100/2025: the cap rule, VI.4, VI.5, VII or 7. gr. 2. mgr. not found")
    return {"version": v.group(2), "as_of": v.group(1), "bands": bands, "cap_from": kg(cap_rule.group(1)), "caps": caps,
            "trailer_pct": {int(vi4.group(2)): int(vi4.group(1)), int(vi4.group(4)): int(vi4.group(3))},
            "clean_from_kg": kg(vi5.group(1)), "clean_pct": int(vi5.group(2)), "clean_years": [int(x) for x in vi5.groups()[2:]],
            "trailer_only_year": int(vii.group(1)), "trailer_only_from_kg": kg(seven.group(1))}


def band_rows(bands, unit, factor, min_kg, cap_from, caps, energy=None):
    """Rows for one vehicle unit: the cap rows by axles (masses above the
    annex's maximum pay the band of the maximum), then the bands."""
    def rate(r):
        return round(r * factor / 100, 4)

    def band_of(mass):
        return next(b for b in bands if mass >= b[0] and (b[1] is None or mass <= b[1]))

    extra = {"energy": energy} if energy else {}
    rows = []
    for i, cap in enumerate(caps):
        if cap < cap_from:
            continue
        axles = {"min_axles": i + 1 if unit == "trailer" else i + 2}
        if i < len(caps) - 1:
            axles["max_axles"] = axles["min_axles"]
        rows.append({"component": "toll", "vehicle_unit": unit, "min_kg": max(cap + 1, min_kg), **axles, "rate": rate(band_of(cap)[2]), **extra})
    for lo, hi, r in bands:
        if hi is not None and hi < min_kg:
            continue
        row = {"component": "toll", "vehicle_unit": unit, "min_kg": max(lo, min_kg), "rate": rate(r), **extra}
        if hi is not None:
            row["max_kg"] = hi
        rows.append(row)
    for row in rows:
        if row["min_kg"] == 0:
            del row["min_kg"]
    return rows


def tables(law):
    b, caps, cf = law["bands"], law["caps"], law["cap_from"]
    clean_from, clean_pct = law["clean_from_kg"], law["clean_pct"]
    periods = [("2026-01-01", "2026-12-31", 2026), ("2027-01-01", "2027-12-31", 2027),
               ("2028-01-01", "2029-12-31", 2028), ("2030-01-01", None, 2030)]
    out = []
    for start, end, y in periods:
        tp = law["trailer_pct"].get(y, 100)
        tmin = law["trailer_only_from_kg"] if y == law["trailer_only_year"] else 3501
        clean = y in law["clean_years"]
        rows = []
        if clean:
            # Clean-energy trucks of 10,000 kg or more and their trailers first: the first row a truck matches is its rate.
            rows += band_rows(b, "motor", clean_pct, clean_from, cf, caps["motor"], CLEAN)
            rows += band_rows(b, "trailer", clean_pct, tmin, cf, caps["trailer"], CLEAN)
        rows += band_rows(b, "motor", 100, 0, cf, caps["motor"])
        rows += band_rows(b, "trailer", tp, tmin, cf, caps["trailer"])
        notes = [f"the trailer at {tp} % of its band" + (f", only trailers of {tmin:,} kg or more" if tmin > 3501 else "")] if tp != 100 or tmin > 3501 else []
        if clean:
            notes.append(f"trucks of {clean_from:,} kg or more running on methane, methanol, electricity or hydrogen, and their trailers, at {clean_pct} %")
        span = str(y) if end and end[:4] == str(y) else f"{y}-{end[:4]}" if end else f"from {y}"
        t = {"country": "IS", "currency": "ISK", "valid_from": start, "name": "Kílómetragjald (km fee on vehicles)",
             "law": (f"Lög um kílómetragjald á ökutæki nr. 100/2025, in Alþingi's lagasafn útgáfa {law['version']} ({law['as_of']}): 6. gr., ISK per km by "
                     "the vehicle's gjaldþyngd, its permissible total weight on registration; from 10,000 kg at most the annex's maximum by axles "
                     f"(motor vehicle {', '.join(f'{c:,}' for c in caps['motor'])} kg with 2, 3, 4 or more axles; trailer {', '.join(f'{c:,}' for c in caps['trailer'])} kg with 1, 2, 3 or more). "
                     "The motor vehicle and the trailer each pay on their own (give motor_mass_kg, trailer_mass_kg and motor_axles); the annex's maxima for road trains are not applied. "
                     + ("Temporary provisions VI and VII for " + span + ": " + "; ".join(notes) + ". " if notes else "")
                     + "Buses' discounts are left out. Foreign vehicles in Iceland pay it too (3. gr.)."),
             "sources": [{"title": "Lög um kílómetragjald á ökutæki nr. 100/2025 (Alþingi, lagasafn)", "url": SOURCE}],
             "vehicles": "All vehicles; trailers over 3,500 kg", "min_kg": 0,
             "tolled_roads": "All roads (by odometer).", "rows": rows}
        if end:
            t["valid_to"] = end
        out.append(t)
    return out


def main(fetched, out):
    p = os.path.join(fetched, "is-althingi-100-2025.html")
    if not os.path.exists(p):
        print("Iceland km fee: law not fetched; not built")
        return
    law = read(text(p))
    os.makedirs(out, exist_ok=True)
    for t in tables(law):
        path = os.path.join(out, f"is-{t['valid_from']}.json")
        json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(t["rows"]), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
