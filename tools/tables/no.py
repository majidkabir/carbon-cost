"""Builds the Norwegian toll station table from the national road
database NVDB (Statens vegvesen), as fetch.py saves it: the toll stations
(object type 45, Bomstasjon: no-nvdb-45*.json) and the road link
sequences they are placed on (no-nvdb-45-links-*.json).

Usage: python3 no.py fetched/ out-dir -> out-dir/no-<date>.json

Each AutoPASS toll station becomes a toll point with:
- its position (geometry, WGS 84; NVDB writes "POINT Z (lat lon h)");
- "Takst stor bil", the price per passage for large vehicles (over
  3,500 kg), and "Rushtidstakst stor bil" where the price is higher in
  rush hours;
- the charged direction ("Innkrevningsretning"): "Begge retninger" or no
  value: both ways; "Med metrering" or "Mot metrering": along or against
  the road link sequence's metering direction, turned into a compass
  heading from the link's geometry (which runs in the metering
  direction) at the station's relative position;
- the hour rule ("Timesregel"): "Første passering gjelder" with its
  passage group and duration: after a paid passage, the group's other
  stations are free for that long (or, where the project's tariff decision
  says so, charge only what their price exceeds the hour's: RUSH);
- the rush hours where "Rushtidstakst stor bil" applies: the hours of the
  project's tariff decision (RUSH), checked against the station's
  "Rushtid morgen/ettermiddag, fra/til" (NVDB writes the end either as the
  last minute, 08:59, or as the end, 09:00), Monday to Friday except
  RUSH_DAYS and the project's own rush-free days.
  A station whose project RUSH lacks, or whose NVDB hours differ, keeps
  only its off-peak price (a warning says so).
- the environmental prices of large vehicles (takstgruppe 2) where the
  project's tariff decision or price page is read (ENV): Euro VI's for the
  station's NVDB price (Euro V and older), off-peak and in rush hours, and
  the zero-emission price (CO2 class 5 here). A station whose NVDB price
  isn't one the source gives keeps it for Euro VI (a warning says so);
  other projects charge every truck NVDB's price.
Stations without a large-vehicle price, ferry collection points and
stations on local or private roads are left out (listed when built). The
table is valid from the latest version date of the stations
(metadata.startdato).
"""
import glob, html, json, math, os, re, sys, unicodedata


# The days without rush-hour prices besides weekends, for every project:
# Norway's public holidays (offentlige fridager: rates.NorwegianHoliday).
RUSH_DAYS = ["norwegian_holidays"]

# Rush-hour pricing by toll project (NVDB "Navn bompengeanlegg"): the rush
# hours of its tariff decision (from, to; the end excluded), its rush-free
# days besides RUSH_DAYS ("norwegian_eves": Christmas Eve, New Year's Eve
# and the Wednesday before Maundy Thursday; "july"), what the hour rule
# charges ("first": the first passage of the hour, AutoPASS's practice,
# Vegdirektoratet 27.09.2018, 15/233884-22; "highest": the hour's highest
# price) and the sources (tools/tables/sources.json ids) with what they
# must still say.
RUSH = {
    "Fjellinjen AS": {
        "hours": [("06:30", "09:00"), ("15:00", "17:00")], "free_days": ["july"], "pays": "highest",
        "check": {"no-rush-fjellinjen": ["06.30 and 09.00", "15.00 and 17.00", "Saturdays, Sundays or public holidays or in July"],
                  "no-rush-fjellinjen-hour": ["høyeste taksten ved flere passeringer med ulik takst innenfor en time"]}},
    "Ferde AS - Bomringen Bergen": {
        "hours": [("06:30", "09:00"), ("14:30", "16:30")], "free_days": [], "pays": "highest",
        "check": {"no-rush-bergen": ["Mandag til fredag i rushtiden kl. 06:30 – 09:00 og 14:30 – 16:30", "lørdag, søndag og helligdager"],
                  "no-rush-bergen-decision": ["høyeste taksten ved flere passeringer med ulik takst innenfor en time"]}},
    "Ferde AS - Bomringen i Kristiansand": {
        "hours": [("06:30", "09:00"), ("14:30", "17:00")], "free_days": [], "pays": "first",
        "check": {"no-rush-kristiansand": ["Rushtid (06:30-", "09:00 og 14:30-17:00)"],
                  "no-rush-kristiansand-days": ["Mandag til fredag i rushtiden kl. 06:30–09:00 og 14:30–17:00", "lørdag, søndag og helligdager"]}},
    "Vegamot AS": {
        "hours": [("07:00", "09:00"), ("15:00", "17:00")], "free_days": ["norwegian_eves"], "pays": "first",
        "check": {"no-rush-vegamot": ["07:00 til 09:00, og 15:00-17:00", "lørdag, søndag eller helligdager", "julaften, nyttårsaften og onsdag før påske"]}},
    "Bypakke Tenk Tromsø - BPS Nord": {
        "hours": [("06:30", "09:00"), ("15:00", "17:00")], "free_days": ["norwegian_eves"], "pays": "first",
        "check": {"no-rush-tromso": ["mandag-fredag kl. 06.30-09:00 og kl. 15.00-17.00", "første registrerte passeringen"],
                  "no-rush-tromso-days": ["offisielle fridager, noe som omfatter julaften, nyttårsaften og onsdag før påske"]}},
    "Vegfinans Bypakke Grenland AS": {
        "hours": [("07:00", "09:00"), ("15:00", "17:00")], "free_days": [], "pays": "first",
        "check": {"no-rush-grenland": ["mandag - fredag kl. 07:00 - 09:00 og kl. 15:00 - 17:00, unntatt offentlige fri- og helgedager"]}},
}


def page_text(fetched, sid):
    f = next((os.path.join(fetched, sid + e) for e in (".txt", ".html") if os.path.exists(os.path.join(fetched, sid + e))), None)
    if f is None:
        return None
    t = open(f, encoding="utf-8", errors="replace").read()
    if f.endswith(".html"):
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


# Environmental prices of large vehicles by project: its sources and how to
# read each, the one in force first: an edition {"off": {Euro V price: Euro
# VI price}, "rush": {...}, "zero": zero-emission price}, or None if the
# source no longer says it. Earlier editions price the history's stations
# whose NVDB price is theirs (build_no.py).
def env_fjellinjen(t):
    m = re.search(r"Tariff group 2: Large car .*? Outside of rush hour NOK (\d+) Euro 5 and older NOK \1 NOK (\d+) Euro 6 NOK \2 NOK (\d+) Zero-emission NOK \3 "
                  r".*? Rush hour NOK (\d+) Euro 5 and older NOK \4 NOK (\d+) Euro 6 NOK \5 NOK (\d+) Zero-emission NOK \6 ", t)
    if not m or m.group(3) != m.group(6):
        return None
    return {"off": {int(m.group(1)): int(m.group(2))}, "rush": {int(m.group(4)): int(m.group(5))}, "zero": int(m.group(3))}


def env_fjellinjen_2025(t):
    m = re.search(r"Takstgruppe 2 .*?Euro V og eldre Euro VI Nullutslipp kjøretøy Passering utenom rush (\d+) (\d+) (\d+) \d+ "
                  r"Passering i rush \([^)]*\) (\d+) (\d+) (\d+) ", t)
    if not m or m.group(3) != m.group(6):
        return None
    return {"off": {int(m.group(1)): int(m.group(2))}, "rush": {int(m.group(4)): int(m.group(5))}, "zero": int(m.group(3))}


def env_bergen(t):
    h = re.search(r"Takstgruppe 1 Takstgruppe 2 Diesel Normaltakst Nullutslipp Euro V og eldre Euro VI Nullutslipp ", t)
    off = re.search(r"Utenfor rushtid \d+ \d+ \d+ (\d+) (\d+) (\d+) ", t)
    rush = re.search(r"Rushtid 1? ?\d+ \d+ \d+ (\d+) (\d+) (\d+) ", t)
    if not (h and off and rush) or off.group(3) != rush.group(3):
        return None
    return {"off": {int(off.group(1)): int(off.group(2))}, "rush": {int(rush.group(1)): int(rush.group(2))}, "zero": int(off.group(3))}


def env_kristiansand(t, n=0):
    # The prices in force come first (n 0), then those that ended (n 1,
    # "Utgåtte priser").
    ms = list(re.finditer(r"Priser, takstgruppe 2 Priser \(kr\) Pris Rushtid \* Euro V og eldre Pris (\d+),00 Rushtid med avtale (\d+),00 Euro VI / hybrid Pris (\d+),00 "
                          r"Rushtid med avtale (\d+),00 Nullutslippskjøretøy Pris (\d+) Rushtid med avtale (\d+) ", t))
    m = ms[n] if len(ms) > n else None
    if not m or m.group(1) != m.group(2) or m.group(3) != m.group(4) or m.group(5) != m.group(6):
        return None  # (rush hours there are takstgruppe 1's only)
    return {"off": {int(m.group(1)): int(m.group(3))}, "rush": {}, "zero": int(m.group(5))}


def env_zero(phrase):
    return lambda t: {"off": {}, "rush": {}, "zero": 0} if phrase in t else None


ENV = {
    "Fjellinjen AS": [("no-rush-fjellinjen", env_fjellinjen), ("no-rush-fjellinjen-hour", env_fjellinjen_2025)],
    "Ferde AS - Bomringen Bergen": [("no-rush-bergen-decision", env_bergen)],
    "Ferde AS - Bomringen i Kristiansand": [("no-rush-kristiansand-days", env_kristiansand), ("no-rush-kristiansand-days", lambda t: env_kristiansand(t, 1))],
    "Vegamot AS": [("no-rush-vegamot", env_zero("Nullutslipps- og gassdrevne kjøretøy i takstgruppe 2 har reduksjon av takst på 100 prosent"))],
    "Bypakke Tenk Tromsø - BPS Nord": [("no-rush-tromso", env_zero("100 prosent takstreduksjon for nullutslippskjøretøy i takstgruppe 2"))],
}
ZERO = {"co2_class": [5]}
EURO6 = {"euro_class": ["6", "7"], "co2_class": [1, 2, 3, 4]}


def env_prices(fetched):
    """{project: [editions, the one in force first]} of the sources read."""
    out = {}
    for project, srcs in ENV.items():
        eds = []
        for k, (sid, read) in enumerate(srcs):
            t = page_text(fetched, sid)
            e = read(t) if t else None
            if e is None:
                print(f"::warning title=no.py::{sid}: the large vehicles' environmental prices not read" + (f"; {project} charges every truck NVDB's price" if k == 0 else ""))
                if k == 0:
                    break
                continue
            eds.append(e)
        if eds:
            out[project] = eds
    return out


def apply_env(tp, env, history=False):
    """The point's environmental prices for large vehicles, if its project
    has them: the edition in force, or in the history the edition whose
    prices the point's are (none if none is: a zero-emission rule alone
    has no date here)."""
    eds = env.get(tp.get("project"))
    if not eds:
        return
    if history:
        e = next((e for e in eds if tp["rate"] in e["off"] and (not tp.get("peak_rate") or not e["rush"] or tp["peak_rate"] in e["rush"])), None)
        if e is None:
            return
    else:
        e = eds[0]
    euro6 = {"rate": e["off"].get(tp["rate"], tp["rate"])}
    if tp.get("peak_rate"):
        euro6["peak_rate"] = e["rush"].get(tp["peak_rate"], tp["peak_rate"])
    if (e["off"] and tp["rate"] not in e["off"]) or (tp.get("peak_rate") and e["rush"] and tp["peak_rate"] not in e["rush"]):
        print(f"::warning title=no.py::{tp['name']}: NVDB's price {tp['rate']}/{tp.get('peak_rate')} isn't one {tp['project']}'s source gives; Euro VI pays it")
    classes = [{"criteria": ZERO, "rate": e["zero"], **({"peak_rate": e["zero"]} if tp.get("peak_rate") else {})}]
    if e["off"]:
        classes.append({"criteria": EURO6, **euro6})
    tp["class_rates"] = classes


def check_rush(fetched):
    """Warns where a rush source no longer says what RUSH was taken from."""
    def norm(t):
        t = unicodedata.normalize("NFKC", t)
        return re.sub(r"\s+", " ", re.sub(r"[‐-―−]", "-", t)).replace(" - ", "-").replace("- ", "-").lower()
    want = {}
    for r in RUSH.values():
        want.update(r["check"])
    for sid, phrases in sorted(want.items()):
        f = next((os.path.join(fetched, sid + e) for e in (".txt", ".html") if os.path.exists(os.path.join(fetched, sid + e))), None)
        if f is None:
            print(f"::warning title=no.py::{sid} not fetched: rush-hour rules not checked")
            continue
        text = open(f, encoding="utf-8", errors="replace").read()
        if f.endswith(".html"):
            text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        text = norm(text)
        for ph in phrases:
            if norm(ph) not in text:
                print(f"::warning title=no.py::{sid} no longer says {ph!r}: check the rush-hour rules (RUSH)")


def hm(v):
    h, m = map(int, v.split(":"))
    return h * 60 + m


def rush(e, project):
    """The station's rush hours (RUSH, both ends included), or None and why."""
    r = RUSH.get(project)
    if r is None:
        return None, "no rush-hour rules for its project"
    nvdb = [(e.get(f"Rushtid {p}, fra"), e.get(f"Rushtid {p}, til")) for p in ("morgen", "ettermiddag")]
    if all(a and b for a, b in nvdb):
        # NVDB's end is the last minute (…:59, …:29) or the end itself.
        got = [(hm(a), hm(b) + 1 if hm(b) % 30 == 29 else hm(b)) for a, b in nvdb]
        if got != [(hm(a), hm(b)) for a, b in r["hours"]]:
            return None, f"NVDB's rush hours {nvdb} differ from the tariff decision's {r['hours']}"
    last = lambda v: f"{(hm(v) - 1) // 60:02d}:{(hm(v) - 1) % 60:02d}"
    return {"hours": [[a, last(b)] for a, b in r["hours"]], "free_days": RUSH_DAYS + r["free_days"]}, None


def props(o):
    return {p["navn"]: p.get("verdi") for p in o.get("egenskaper", [])}


def links(fetched):
    out = {}
    for f in sorted(glob.glob(os.path.join(fetched, "no-nvdb-45-links-*.json"))):
        d = json.load(open(f))
        for s in d.get("objekter", d if isinstance(d, list) else []):
            out[s["veglenkesekvensid"]] = s
    return out


def coords(wkt):
    return [tuple(map(float, p.split()[:2])) for p in re.search(r"\((.*)\)", wkt).group(1).split(",")]


def heading_at(seq, rel, closed=False):
    """Compass heading of the metering direction at relative position rel,
    on the links in use (closed: also on links no longer in use)."""
    for v in seq.get("veglenker", []):
        if (v.get("sluttdato") and not closed) or not (v["startposisjon"] <= rel <= v["sluttposisjon"]):
            continue
        pts = coords(v["geometri"]["wkt"])  # (lat, lon), in metering direction
        if len(pts) < 2:
            continue
        f = (rel - v["startposisjon"]) / (v["sluttposisjon"] - v["startposisjon"])
        seg = [math.hypot((b[0] - a[0]) * 111.2, (b[1] - a[1]) * 111.2 * math.cos(math.radians(a[0]))) for a, b in zip(pts, pts[1:])]
        target, cum = f * sum(seg), 0.0
        for (a, b), l in zip(zip(pts, pts[1:]), seg):
            if cum + l >= target and l > 0:
                dy, dx = (b[0] - a[0]) * 111.2, (b[1] - a[1]) * 111.2 * math.cos(math.radians(a[0]))
                return round(math.degrees(math.atan2(dx, dy)) % 360, 1)
            cum += l
    return None


def point(o, seqs, closed=False):
    """The toll point of an NVDB Bomstasjon object, or None and why not."""
    e = props(o)
    name = (e.get("Navn bomstasjon") or "").strip() or f"NVDB {o['id']}"
    kind = e.get("Bomstasjonstype")
    if kind != "AutoPASS bomstasjon":
        return None, f"{name} ({kind})"
    if e.get("Takst stor bil") is None:
        return None, f"{name} (no large-vehicle price)"
    lat, lon = coords(o["geometri"]["wkt"])[0]
    tp = {"name": name}
    if e.get("Navn bompengeanlegg"):
        tp["project"] = e["Navn bompengeanlegg"].strip()
    tp.update(lat=round(lat, 6), lon=round(lon, 6))
    way = e.get("Innkrevningsretning")
    if way in ("Med metrering", "Mot metrering"):
        st = next((s for s in o["lokasjon"]["stedfestinger"] if s.get("veglenkesekvensid") in seqs), None)
        h = heading_at(seqs[st["veglenkesekvensid"]], st["relativPosisjon"]) if st else None
        if h is None and st and closed:
            h = heading_at(seqs[st["veglenkesekvensid"]], st["relativPosisjon"], closed=True)
        if h is None:
            return None, f"{name} (charged direction not found on its road link)"
        if way == "Mot metrering":
            h = round((h + 180) % 360, 1)
        tp["heading"] = h
    tp["rate"] = e["Takst stor bil"]
    if (e.get("Rushtidstakst stor bil") or 0) > tp["rate"]:
        tp["peak_rate"] = e["Rushtidstakst stor bil"]
        r, why = rush(e, tp.get("project"))
        if r:
            tp["rush"] = r
        else:
            print(f"::warning title=no.py::{name}: priced off-peak only: {why}")
    if e.get("Timesregel") == "Første passering gjelder" and e.get("Timesregel, passeringsgruppe"):
        tp["group"] = e["Timesregel, passeringsgruppe"]
        tp["group_minutes"] = e.get("Timesregel, varighet") or 60
        if RUSH.get(tp.get("project"), {}).get("pays") == "highest":
            tp["group_pays"] = "highest"
    return tp, None


def rush_sources():
    src = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json"), encoding="utf-8"))["sources"]}
    ids = [i for r in RUSH.values() for i in r["check"]]
    return [{"title": src[i]["what"], "url": src[i]["url"]} for i in ids]


def main(fetched, out):
    objs = []
    for f in sorted(glob.glob(os.path.join(fetched, "no-nvdb-45*.json"))):
        if "-links-" in f:
            continue
        objs += json.load(open(f)).get("objekter", [])
    seqs = links(fetched)
    check_rush(fetched)
    env = env_prices(fetched)
    points, left_out, dates = [], [], []
    for o in sorted(objs, key=lambda o: o["id"]):
        tp, why = point(o, seqs)
        if tp is None:
            left_out.append(why)
            continue
        apply_env(tp, env)
        points.append(tp)
        dates.append(o["metadata"]["startdato"])
    valid_from = max(dates)
    tb = {
        "country": "NO", "currency": "NOK", "valid_from": valid_from,
        "name": "Norwegian road tolls (bompenger, AutoPASS toll stations)",
        "law": "Veglova § 27 and the toll projects' Storting decisions; prices per passage for large vehicles (takstgruppe 2, over 3,500 kg) as registered for each AutoPASS toll station in NVDB, Statens vegvesen's national road database (object type 45 Bomstasjon), with the charged direction and the hour rule (timesregel: after a paid passage the project's other stations are free for the time given; where the tariff decision says so, at Fjellinjen and in Bypakke Bergen, the hour's highest price is charged). Rush-hour prices (Rushtidstakst stor bil) apply in the rush hours of each project's tariff decision, Monday to Friday except public holidays (the helligdager of helligdagsfredloven § 2, and 1 and 17 May, which lov 26. april 1947 nr. 1 equates with Sundays); in Miljøpakke Trondheim (Vegamot) and Bypakke Tenk Tromsø also not on Christmas Eve, New Year's Eve and the Wednesday before Easter, at Fjellinjen not in July, as each project's rules say. Large vehicles' environmental prices (Euro VI, zero-emission) as the tariff decisions or price pages of " + ", ".join(sorted(env)) + " give them; elsewhere every truck pays NVDB's price. Tolls carry no VAT.",
        "sources": [{"title": "NVDB API: Bomstasjon (Statens vegvesen)", "url": "https://nvdbapiles.atlas.vegvesen.no/vegobjekter/api/v4/vegobjekter/45"}] + rush_sources(),
        "vehicles": "Vehicles over 3,500 kg (takstgruppe 2)",
        "min_kg": 3501,
        "tolled_roads": f"{len(points)} AutoPASS toll stations, each charged when the route passes it in a charged direction.",
        "toll_points": points,
        "rows": [],
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"no-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(points), "toll points; left out:", "; ".join(left_out))


if __name__ == "__main__":
    main(*sys.argv[1:])
