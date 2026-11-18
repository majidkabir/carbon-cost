#!/usr/bin/env python3
"""Converts the rate tables carbon-cost's builders write (tools/tables,
tools/history, tools/fr, tools/hr: one JSON table each) to ORCT 0.3, the
only form carbon-cost keeps and prices with.

Usage: convert.py <tables dir> <out dir> [--commit SHA]
       convert.py --index <out dir>

Writes <out dir>/<country>/<table>.orct.json for each table, and
<out dir>/index.json listing every dataset there (--index: only that). What
ORCT can't express yet is kept under the carbon-cost extension and listed in
coverage as partial, so nothing is lost and a calculator knows what it would
miss. The meaning of each table field is documented in tools/orct/TABLES.md.
"""
import hashlib
import json
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal

REPO = "https://github.com/majidkabir/carbon-cost"
EXT = "io.github.majidkabir.carboncost"
TZ = {
    "AL": "Europe/Tirane", "AT": "Europe/Vienna", "BA": "Europe/Sarajevo", "BE": "Europe/Brussels",
    "BG": "Europe/Sofia", "CH": "Europe/Zurich", "CZ": "Europe/Prague", "DE": "Europe/Berlin",
    "DK": "Europe/Copenhagen", "EE": "Europe/Tallinn", "ES": "Europe/Madrid", "FR": "Europe/Paris",
    "GB": "Europe/London", "GR": "Europe/Athens", "HR": "Europe/Zagreb", "HU": "Europe/Budapest",
    "IE": "Europe/Dublin", "IT": "Europe/Rome", "LI": "Europe/Vaduz", "LT": "Europe/Vilnius",
    "LU": "Europe/Luxembourg", "LV": "Europe/Riga", "MD": "Europe/Chisinau", "ME": "Europe/Podgorica",
    "MK": "Europe/Skopje", "NL": "Europe/Amsterdam", "NO": "Europe/Oslo", "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon", "RO": "Europe/Bucharest", "RS": "Europe/Belgrade", "SE": "Europe/Stockholm",
    "SI": "Europe/Ljubljana", "SK": "Europe/Bratislava", "TR": "Europe/Istanbul",
    "FI": "Europe/Helsinki", "IS": "Atlantic/Reykjavik", "AD": "Europe/Andorra", "FO": "Atlantic/Faroe",
    "BY": "Europe/Minsk",
}
COMPONENT = {
    "infrastructure": "infrastructure", "air": "air_pollution", "noise": "noise",
    "air_noise": "air_pollution_noise", "co2": "co2", "congestion": "congestion",
}
ROW_KEYS = ["object", "entry", "exit", "vehicle_class", "user_class", "time_class", "product", "priority", "amount"]


def dec(x):
    """A number from carbon-cost as an ORCT decimal string."""
    d = Decimal(repr(x)) if isinstance(x, float) else Decimal(x)
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def component(c):
    """carbon-cost component -> (ORCT component, label kept when not a direct match)."""
    if c in COMPONENT:
        return COMPONENT[c], None
    if c in ("toll", "km_charge", "distance_fee"):
        return "unspecified", c
    return "other", c


def plus_minute(hhmm):
    """carbon-cost's inclusive end minute as ORCT's exclusive end."""
    h, m = map(int, hhmm.split(":"))
    h, m = h + (m + 1) // 60, (m + 1) % 60
    return "24:00" if (h, m) >= (24, 0) else f"{h:02d}:{m:02d}"


def rng(lo=None, hi=None, gt=None):
    r = {}
    if lo:
        r["min"] = lo
    if gt:
        r["gt"] = gt
    if hi:
        r["max"] = hi
    return r or None


def lonlat(p):
    return [p["lon"], p["lat"]]


def place(p):
    out = {"geometry": {"type": "Point", "coordinates": lonlat(p)}}
    if p.get("name"):
        out["name"] = p["name"]
    if p.get("heading") is not None:
        out["heading"] = p["heading"]
    return out


def clean(d):
    return {k: v for k, v in d.items() if v not in (None, [], {})}


def hours(h):
    return [[h[0], plus_minute(h[1])]]


UNIT_PARAMS = {"": ("train_mass_kg", "train_axles"), "motor": ("mass_kg", "axles"), "trailer": ("trailer_mass_kg", "trailer_axles")}


def criteria_of(r, motor_axles=False):
    """carbon-cost row, group or point-class bounds as ORCT criteria.

    carbon-cost classifies by one mass, the technically permissible maximum
    mass of the truck with its trailer, and by the combination's axles unless
    the table counts the motor vehicle's (motor_axles); a row with a
    vehicle_unit ("motor" or "trailer") bounds that vehicle's own mass and
    axles instead (a charge each vehicle of a combination pays)."""
    mass, axles = UNIT_PARAMS[r.get("vehicle_unit", "")]
    if motor_axles and not r.get("vehicle_unit"):
        axles = "axles"
    c = {mass: rng(r.get("min_kg"), r.get("max_kg")), axles: rng(r.get("min_axles"), r.get("max_axles"))}
    if r.get("energy"):
        c["energy"] = r["energy"]
    if "trailer" in r:
        c["trailer"] = bool(r["trailer"])
    if r.get("min_length_m") or r.get("max_length_m"):
        c["train_length_m"] = rng(hi=r.get("max_length_m"), gt=r.get("min_length_m"))
    if r.get("min_capacity_kg") is not None or r.get("max_capacity_kg"):
        c["load_capacity_kg"] = rng(hi=r.get("max_capacity_kg"), gt=r.get("min_capacity_kg"))
    if r.get("euro"):
        c["euro_class"] = euro_list(r["euro"])
    if r.get("co2_class"):
        c["co2_class"] = r["co2_class"]
    return clean(c)


def euro_list(euros, or_later=False):
    """carbon-cost Euro numbers as ORCT euro classes: carbon-cost counts EEV as Euro V,
    and "this standard or a later one" includes Euro 7."""
    out = [str(e) for e in sorted(euros)]
    if 5 in euros:
        out.insert(out.index("5") + 1, "EEV")
    if or_later and 6 in euros:
        out.append("7")
    return out


def season_days(s):
    """carbon-cost's Season is the union of its months, its weekdays (0 = Sunday) and its Easter window."""
    out = []
    if s.get("months"):
        out.append({"months": s["months"]})
    if s.get("weekdays"):
        out.append({"weekdays": sorted(7 if w == 0 else w for w in s["weekdays"])})
    if s.get("easter_from") or s.get("easter_to"):
        out.append({"easter": [[s.get("easter_from", 0), s.get("easter_to", 0)]]})
    return out


class Builder:
    def __init__(self, t, path):
        self.t = t
        stem = os.path.basename(path)[:-5]
        scheme = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", stem)
        self.header = {
            "id": f"carbon-cost/{scheme}/{t['valid_from']}",
            "scheme": clean({"id": scheme, "name": t["name"], "country": t["country"], "region": t.get("region")}),
            "publisher": {"name": "carbon-cost", "role": "third_party", "url": REPO},
            "valid_from": t["valid_from"],
            "valid_to": t.get("valid_to") or None,
            "currency": t["currency"],
            "timezone": TZ[t["country"]],
            "license": "MIT",
            "method": t.get("law", ""),
            "derived_from": {"url": REPO, "path": os.path.basename(path)},  # the table, as the builders write it
        }
        self.sources = [{"id": f"s{i + 1}", "title": s["title"], "url": s["url"]} for i, s in enumerate(t.get("sources", []))]
        if not self.sources:
            self.sources = [{"id": "s0", "title": "carbon-cost rate table " + os.path.basename(path), "url": REPO}]
        self.src = [s["id"] for s in self.sources]
        self.basis = "estimated" if ("ESTIMATE" in t.get("name", "") or t.get("law", "").startswith("Estimate")) else "transcribed"
        self.sets, self.set_keys, self.class_ids = [], {}, set()
        self.times, self.time_keys = [], {}
        self.users = {}
        self.objects, self.object_ids = [], set()
        self.charges, self.rules, self.coverage, self.ext = [], [], [], {}
        self.calendars = []
        self.features = set()

    def class_set(self, prefix, classes):
        """classes: [(criteria, label, fallback label)] -> class ids, reusing an identical set."""
        key = json.dumps([[c, l, f] for c, l, f in classes], sort_keys=True)
        if key in self.set_keys:
            return self.set_keys[key]
        n = 1
        while f"{prefix}{n}" in {s["id"] for s in self.sets}:
            n += 1
        sid = f"{prefix}{n}"
        ids, by_label = [], {}
        for i, (_, label, _) in enumerate(classes):
            cid = f"{sid}.{re.sub(r'[^A-Za-z0-9+]+', '-', label).strip('-') if label else i + 1}"
            while cid in self.class_ids:
                cid += "_"
            self.class_ids.add(cid)
            ids.append(cid)
            by_label[label] = cid
        out = []
        for (crit, label, fb), cid in zip(classes, ids):
            c = {"id": cid, **({"label": label} if label else {}), "criteria": crit}
            if fb and fb in by_label:
                c["fallback"] = by_label[fb]
            out.append(c)
        self.sets.append({"id": sid, "classes": out})
        self.set_keys[key] = ids
        return ids

    def time_class(self, hint, days=None, times=None, defined=True, label=None, note=None):
        body = clean({"days": [clean(d) for d in days or []], "times": times, "defined": None if defined else False, "note": note})
        key = json.dumps(body, sort_keys=True)
        if key in self.time_keys:
            return self.time_keys[key]
        tid, n = hint, 1
        while tid in {x["id"] for x in self.times}:
            n += 1
            tid = f"{hint}-{n}"
        self.times.append({"id": tid, **({"label": label} if label else {}), **body})
        self.time_keys[key] = tid
        self.features.add("time_classes")
        return tid

    def electronic(self):
        self.users["electronic"] = {"id": "electronic", "label": "Electronic toll device or contract", "payment": ["electronic"]}
        self.features.add("user_classes")
        return "electronic"

    def obj(self, o):
        if o["id"] not in self.object_ids:
            self.object_ids.add(o["id"])
            self.objects.append(clean(o))
        return o["id"]

    def charge(self, ch, rows):
        keys = [k for k in ROW_KEYS if k == "amount" or any(r.get(k) is not None for r in rows)]
        ch["columns"] = keys
        ch["rows"] = [[r.get(k) for k in keys] for r in rows]
        ch.setdefault("sources", self.src)
        ch.setdefault("basis", self.basis)
        self.charges.append(ch)
        self.features.add("type." + ch["type"])
        if ch.get("rounding"):
            self.features.add("rounding")
        return ch["id"]

    def rule(self, kind, applies_to, params):
        self.rules.append({"id": f"r{len(self.rules) + 1}", "kind": kind, "applies_to": applies_to, "params": params})
        self.features.add("rule." + kind)

    def partial(self, scope, reason):
        self.coverage.append({"scope": scope, "status": "partial", "reason": reason})

    def calendar(self, cid, name, dates, covers_to):
        self.calendars.append({"id": cid, "name": name, "dates": dates, "covers_to": covers_to})
        self.features.add("calendars")
        return cid

    def keep(self, key, value, reason=None):
        self.ext[key] = value
        if reason:
            self.partial("dataset", reason)

    def doc(self, liable):
        if self.basis == "estimated":
            self.partial("dataset", "the source table is an estimate; see dataset.method")
        header = clean(self.header)
        header["required_features"] = sorted(self.features)
        out = {
            "orct": "0.3",
            "dataset": header,
            "sources": self.sources,
            "tax": {"basis": "unknown", "note": "carbon-cost states the tax basis in each table's text (dataset.method), not as a field."},
            "liable_vehicles": liable,
            "vehicle_class_sets": self.sets or [{"id": "all", "classes": [{"id": "any", "criteria": {}}]}],
            "time_classes": self.times,
            "calendars": self.calendars,
            "user_classes": list(self.users.values()),
            "charge_objects": self.objects,
            "charges": self.charges,
            "rules": self.rules,
            "coverage": self.coverage or [{"scope": "dataset", "status": "complete"}],
        }
        if self.ext:
            out["extensions"] = {EXT: self.ext}
        return {k: v for k, v in out.items() if v != [] or k in ("charges", "charge_objects")}


# --- toll tables ---------------------------------------------------------------

def convert_table(t, path):
    b = Builder(t, path)
    used = {"country", "region", "currency", "valid_from", "valid_to", "name", "law", "sources", "vehicles",
            "min_kg", "tolled_roads", "motor_axles", "rows", "per_tonne_km", "max_chargeable_kg", "per_day", "day",
            "exemptions", "surcharges", "closed_systems", "toll_points", "point_match_km", "sections", "congestion",
            "motorway_share", "suburban_share", "crossings", "osm_extract", "env_zone_surcharge"}
    motor = bool(t.get("motor_axles"))
    liable = {"description": t.get("vehicles", ""), "criteria": clean({"train_mass_kg": rng(t.get("min_kg"))})}

    row_charges = convert_rows(b, t, motor)
    # carbon-cost's exemptions don't reach the environmental-zone surcharge.
    all_rows = sorted({c for comp, ids in row_charges.items() if comp != "env_zone_surcharge" for c in ids})
    for e in t.get("exemptions", []):
        b.rule("exemption", all_rows, {"criteria": {"co2_class": e["co2_class"]}, "until": e["until"], "note": e.get("note", "")})
    for s in t.get("surcharges", []):
        oid = b.obj({"id": "stretch:" + s["id"], "type": "network", "name": s["name"],
                     "location": {"geometry": {"type": "LineString", "coordinates": [lonlat(p) for p in s["points"]]},
                                  "point_names": [p["name"] for p in s["points"]]}})
        # A surcharge of s["factor"] (0.25 = 25 % more) multiplies the km on the stretch by 1 + factor.
        b.rule("factor", row_charges.get(s["component"], []), {"object": oid, "factor": dec(Decimal(repr(s["factor"])) + 1),
                                                              "note": s.get("law", "")})

    systems = {s["name"]: convert_system(b, i, s, motor) for i, s in enumerate(t.get("closed_systems", []), 1)}
    convert_points(b, t, systems, motor)
    if t.get("sections"):
        convert_sections(b, t["sections"], row_charges)

    # How carbon-cost estimates road types a request doesn't give, and source facts: not tariff rules.
    for k in ("motorway_share", "suburban_share", "crossings", "osm_extract"):
        if k in t:
            b.keep(k, t[k])
    for k in sorted(set(t) - used):
        b.keep(k, t[k], f"{k} is kept as an extension (no ORCT field yet)")
    return b.doc(liable)


def convert_rows(b, t, motor):
    """Rate rows: one charge per component, keyed by network object and vehicle class."""
    if not t.get("rows"):
        return {}
    roads = b.obj({"id": "roads", "type": "network", "network": {"description": t.get("tolled_roads", "")}})

    def road_obj(road):
        return b.obj({"id": "road:" + road, "type": "network", "parents": [roads],
                      "network": {"road_types": ["motorway" if road == "motorway" else "other"]}})

    def area_obj(area):
        return b.obj({"id": "road:" + area, "type": "network", "parents": [roads], "network": {"area": area}})

    # Road type and area are two independent dimensions: a km is on one road type and in one area, so the
    # cells "road:<type>:<area>" have both as parents and reach the rows of each.
    road_types = sorted({r.get("road") for r in t["rows"] if r.get("road")} | ({"motorway"} if any(r.get("operator") for r in t["rows"]) else set()))
    areas = sorted({r.get("area") for r in t["rows"] if r.get("area")})
    for rt in road_types:
        for area in areas:
            b.obj({"id": f"road:{rt}:{area}", "type": "network", "parents": [road_obj(rt), area_obj(area)],
                   "network": {"road_types": ["motorway" if rt == "motorway" else "other"], "area": area}})
    groups = {}
    for r in t["rows"]:
        road, area, op = r.get("road", ""), r.get("area", ""), r.get("operator", "")
        if r["component"] == "env_zone_surcharge":
            # Charged on the km a trip drives on tolled roads inside environmental zones, given apart.
            oid = b.obj({"id": "env-zones", "type": "network", "name": "Tolled roads in environmental zones",
                         "network": {"description": t.get("env_zone_surcharge", "Tolled roads in environmental zones")}})
        elif op:  # an operator's rows apply to motorway km on its ways
            oid = road_obj("motorway")
            parts = op.split("|")
            for n in range(1, len(parts) + 1):
                o = {"id": "op:" + "|".join(parts[:n]), "type": "network", "parents": [oid], "operator": parts[0]}
                if n >= 2:
                    o["road"] = parts[1]
                if n == 3:
                    o["name"] = parts[2]
                oid = b.obj(o)
        elif road and area:
            oid = f"road:{road}:{area}"
        elif road:
            oid = road_obj(road)
        elif area:
            oid = area_obj(area)
        else:
            oid = roads
        groups.setdefault((r["component"], r.get("vehicle_unit", "")), {}).setdefault(oid, []).append(r)

    out = {}
    for (comp, unit), by_obj in groups.items():
        orct_comp, label = component(comp)
        rows = []
        for oid, rs in by_obj.items():
            seen, uniq = {}, []
            for r in rs:
                k = json.dumps(criteria_of(r, motor), sort_keys=True)
                if k in seen:
                    if seen[k] != r["rate"]:
                        b.partial(oid, f"two {comp} rates for one class; the first is kept")
                    continue
                seen[k] = r["rate"]
                uniq.append(r)
            ids = b.class_set(comp + ("-" + unit if unit else "") + "-", [(criteria_of(r, motor), None, None) for r in uniq])
            rows += [{"object": oid, "vehicle_class": cid, "amount": dec(r["rate"])} for cid, r in zip(ids, uniq)]
        ch = {"id": comp + ("-" + unit if unit else ""), "type": "distance", "component": orct_comp, "unit": "km"}
        if label:
            ch["component_label"] = label
        if unit == "trailer":
            # A vehicle without a trailer, or with one lighter than the rows, owes nothing for it.
            ch["unmatched"] = "free"
        if t.get("per_tonne_km"):
            ch["unit"], ch["mass_basis"] = "tkm", "train_mass_kg"
            if t.get("max_chargeable_kg"):
                ch["mass_cap_kg"] = t["max_chargeable_kg"]
        elif t.get("per_day"):
            ch.update(type="period", unit="product")
            for r in rows:
                r["product"] = "P1D"
            if t.get("day") in ("calendar", "24h"):
                ch["day_basis"] = "calendar" if t["day"] == "calendar" else "rolling"
            else:
                b.partial(comp, "the sources don't say whether a day is a calendar day or 24 hours")
        out.setdefault(comp, []).append(b.charge(ch, rows))
    return out


def convert_system(b, i, s, motor=False):
    cid = f"system{i}"
    stations = {}
    for st in s["stations"]:
        loc = {"geometry": {"type": "MultiPoint", "coordinates": [lonlat(p) for p in st["points"]]},
               "point_names": [p.get("name", "") for p in st["points"]]}
        if any(p.get("heading") is not None for p in st["points"]):
            loc["headings"] = [p.get("heading") for p in st["points"]]
        if s.get("station_match_km"):
            loc["match_m"] = round(s["station_match_km"] * 1000)
        stations[st["name"]] = b.obj({"id": f"st{i}:{st['name']}", "type": "station", "name": st["name"], "location": loc})
    names = [g["name"] for g in s["groups"]]
    gid = dict(zip(names, b.class_set(f"sys{i}-", [(criteria_of(g, motor), g["name"], g.get("base")) for g in s["groups"]])))
    etc, night = s.get("etc_prices") or {}, s.get("night_prices") or {}
    tnight = b.time_class(f"sys{i}-night", times=hours(s["night_hours"]), label="Night tariff") if s.get("night_hours") else None
    season = s.get("season_prices") or {}
    tseason = b.time_class(f"sys{i}-season", days=[{"date_ranges": s["season"]}], label="Season") if s.get("season") else None
    rows, odd, unplaced = [], {}, set()
    # At night the night prices replace both the prices and the electronic prices; in the season the season's.
    for table, extra in ((s["prices"], {}), (etc, {"user_class": "electronic"}), (night, {"time_class": tnight, "priority": 1}),
                         (season, {"time_class": tseason, "priority": 1})):
        if table is etc and etc:
            b.electronic()
        for key in sorted(table):
            entry, exit_ = key.split("|")
            for name in (entry, exit_):
                if name not in stations:
                    stations[name] = b.obj({"id": f"st{i}:{name}", "type": "station", "name": name})
                    unplaced.add(name)
            for g, price in sorted(table[key].items()):
                if g not in gid:
                    odd.setdefault(key, {})[g] = price
                    continue
                rows.append({"entry": stations[entry], "exit": stations[exit_], "vehicle_class": gid[g], **extra,
                             "amount": dec(price)})
    if s.get("free_hours"):
        tfree = b.time_class(f"sys{i}-free", times=hours(s["free_hours"]), label="No charge")
        rows.append({"time_class": tfree, "priority": 2, "amount": "0"})
    ch = {"id": cid, "name": s["name"], "type": "od", "component": "unspecified", "unit": "trip"}
    if s.get("unit") == "t":
        # A fare per tonne of a mass (Jadrolinija: of the load capacity).
        ch["unit"], ch["mass_basis"] = "t", s.get("mass_basis", "train_mass_kg")
    if s.get("unmatched"):
        ch["unmatched"] = s["unmatched"]
    if s.get("law"):
        ch["method"] = s["law"]
    if s.get("directed"):
        ch["directed"] = True
    if s.get("chain"):
        b.ext.setdefault("chain_systems", []).append(cid)
        b.partial(cid, "carbon-cost splits a trip through several concessions into tickets by a rule of its own that no "
                       "source states; here a trip is priced from its first station to its last, which only pairs the "
                       "tariff prices")
    if s.get("discounts") and all(Decimal(r["amount"]).as_tuple().exponent >= -2 for r in rows):
        # carbon-cost rounds a discounted price to the cent; with whole-cent prices that is the same as
        # rounding every line.
        ch["rounding"] = {"increment": "0.01", "mode": "half_up", "stage": "line"}
    b.charge(ch, rows)
    for d in s.get("discounts", []):
        p = {"name": d["name"], "percent": dec(d["percent"])}
        if d.get("etc"):
            p["payment"] = ["electronic"]
        # carbon-cost: a discount with both lists applies to a truck in either (Discount.Applies)
        alts = [c for c in ({"euro_class": euro_list(d.get("euro", []))}, {"co2_class": d.get("co2_class")})
                if any(c.values())]
        if len(alts) == 2:
            p["criteria"] = {"any_of": alts}
        elif alts:
            p["criteria"] = alts[0]
        b.rule("discount", [cid], p)
    if unplaced:
        b.partial(cid, f"{len(unplaced)} stations in the tariff aren't placed on the map; their pairs can't be matched to a route")
        for name in sorted(unplaced):
            b.partial(stations[name], "the tariff prices this station but no source places it")
    if odd:
        b.ext.setdefault("closed_system_prices_not_mapped", {})[s["name"]] = odd
        b.partial(cid, "some prices name a vehicle group the system doesn't list; kept as an extension")
    return cid


# Swedish congestion tax days (Lag 2004:629), reckoned as carbon-cost's rates/congestion.go does, listed to
# CALENDAR_TO; a passage after it is reported incomplete (spec 6.7).
CALENDAR_TO = "2035-12-31"


def easter_sunday(y):
    """Anonymous Gregorian algorithm, as congestion.go."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(y, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def se_holidays(y):
    """The public holidays of Lag (1989:253) other than ordinary Sundays (congestion.go's SwedishHolidays)."""
    e = easter_sunday(y)

    def saturday_from(m, d):
        x = date(y, m, d)
        return x + timedelta((5 - x.weekday()) % 7)
    return {"new_year": date(y, 1, 1), "epiphany": date(y, 1, 6), "good_friday": e - timedelta(2), "easter": e,
            "easter_monday": e + timedelta(1), "may_1": date(y, 5, 1), "ascension": e + timedelta(39),
            "pentecost": e + timedelta(49), "june_6": date(y, 6, 6), "midsummer": saturday_from(6, 20),
            "all_saints": saturday_from(10, 31), "christmas": date(y, 12, 25), "boxing_day": date(y, 12, 26)}


def se_taxed(c, d):
    """congestion.go's Congestion.Taxed."""
    if d.weekday() >= 5 or d in se_holidays(d.year).values():
        return False
    n = d + timedelta(1)
    if any(h == n and k not in c.get("eve_taxed", []) for k, h in se_holidays(n.year).items()):
        return False
    if d.month == 7 and c.get("july") == "free":
        return False
    if d.month == 7 and c.get("july") == "first5" and sum(date(d.year, 7, x).weekday() < 5 for x in range(1, d.day + 1)) > 5:
        return False
    return True


def se_high(c, d):
    """congestion.go's Congestion.High."""
    def md(x):
        if x == "midsummer_eve-1":
            return se_holidays(d.year)["midsummer"] - timedelta(2)
        return date(d.year, int(x[:2]), int(x[3:]))
    return any(md(a) <= d <= md(z) for a, z in c.get("high_season", []))


def congestion_days(b, t):
    """The calendar of weekdays without the tax, and the high season as date ranges, from the table's start."""
    if not hasattr(b, "_congestion_days"):
        c = t["congestion"]
        d, end = date.fromisoformat(t["valid_from"]), date.fromisoformat(min(t.get("valid_to") or CALENDAR_TO, CALENDAR_TO))
        free, high, run = [], [], None
        while d <= end:
            if d.weekday() < 5 and not se_taxed(c, d):
                free.append(d.isoformat())
            if se_high(c, d):
                run = [run[0], d.isoformat()] if run else [d.isoformat(), d.isoformat()]
            elif run:
                high.append(run)
                run = None
            d += timedelta(1)
        if run:
            high.append(run)
        cal = b.calendar("no-tax", "Weekdays without the tax: public holidays, the days before them and July as the act says",
                         free, end.isoformat())
        b._congestion_days = (cal, high)
    return b._congestion_days


# Norway's public holidays (rates.NorwegianHoliday) and the eves some
# projects add (rates.NorwegianEve: Christmas Eve, New Year's Eve, the
# Wednesday before Maundy Thursday), as dates every year and days from
# Easter Sunday.
NO_HOLIDAYS = {"dates": ["01-01", "05-01", "05-17", "12-25", "12-26"], "easter": [[-3, -2], [1, 1], [39, 39], [50, 50]]}
NO_EVES = {"dates": ["12-24", "12-31"], "easter": [[-4, -4]]}


def rush_class(b, r):
    """carbon-cost's Rush (rates/rush.go) as a time class: its hours, Monday to Friday, without its free days."""
    free = set(r.get("free_days") or [])
    unknown = free - {"norwegian_holidays", "norwegian_eves", "july"}
    if unknown:
        raise SystemExit(f"rush free days {sorted(unknown)} aren't converted")
    day, ex, words = {"weekdays": [1, 2, 3, 4, 5]}, {"dates": [], "easter": []}, []
    for key, sel, word in (("norwegian_holidays", NO_HOLIDAYS, "public holidays"),
                           ("norwegian_eves", NO_EVES, "Christmas Eve, New Year's Eve and the Wednesday before Maundy Thursday")):
        if key in free:
            ex["dates"] += sel["dates"]
            ex["easter"] += sel["easter"]
            words.append(word)
    if ex["dates"]:
        day["exclude"] = {"dates": sorted(ex["dates"]), "easter": sorted(ex["easter"])}
    if "july" in free:
        day["months"] = [m for m in range(1, 13) if m != 7]
    label = "Rush hours, Monday to Friday" + (" except " + " and ".join(words) if words else "") + ("; not in July" if "july" in free else "")
    return b.time_class("rush", days=[day], times=[hours(h)[0] for h in r["hours"]], label=label)


def convert_points(b, t, systems, motor):
    points = t.get("toll_points", [])
    if not points:
        return
    cong = t.get("congestion") or {}
    match_m = round(t["point_match_km"] * 1000) if t.get("point_match_km") else None
    by_window, groups, peak, sched_points, oids = {}, {}, 0, [], []
    for j, p in enumerate(points, 1):
        loc = {"geometry": {"type": "Point", "coordinates": lonlat(p)}}
        if p.get("heading") is not None:
            loc["heading"] = p["heading"]
        if match_m:
            loc["match_m"] = match_m
        oid = b.obj({"id": f"pt{j}", "type": "point", "name": p["name"], "location": loc,
                     "note": ("Toll project: " + p["project"]) if p.get("project") else None})
        oids.append(oid)
        rows = []
        thigh = b.time_class("high-season", days=season_days(p["high_season"]), label="High season") if p.get("high_season") else None
        tnight = b.time_class("night", times=hours(p["night_hours"]), label="Night") if p.get("night_hours") else None
        if p.get("schedule"):
            sched = cong.get("schedules", {}).get(p["schedule"])
            if sched is None:
                b.partial(oid, f"schedule {p['schedule']} isn't in the table")
            no_tax, high = congestion_days(b, t)
            for ta in sched or []:
                hint, times = f"{p['schedule']}-{ta['from'].replace(':', '')}", [[ta["from"], plus_minute(ta["to"])]]
                split = high and ta.get("high") and ta["high"] != ta["amount"]
                tc = b.time_class(hint, times=times, days=[{"weekdays": [1, 2, 3, 4, 5], "exclude": clean(
                    {"calendars": [no_tax], "date_ranges": high if split else None})}])
                rows.append({"object": oid, "time_class": tc, "amount": dec(ta["amount"])})
                if split:
                    th = b.time_class(hint + "-high", times=times, days=[{"weekdays": [1, 2, 3, 4, 5], "date_ranges": high,
                                                                          "exclude": {"calendars": [no_tax]}}])
                    rows.append({"object": oid, "time_class": th, "amount": dec(ta["high"])})
            sched_points.append(oid)
        elif p.get("classes"):
            ids = b.class_set("pt-", [(criteria_of(c, motor), None, None) for c in p["classes"]])
            for cid, c in zip(ids, p["classes"]):
                base = {"object": oid, "vehicle_class": cid}
                rows.append({**base, "amount": dec(c["rate"])})
                # The night rate replaces the day's (electronic or high-season) rate.
                variants = [("etc_rate", None, True, None), ("high_rate", thigh, False, None),
                            ("high_etc_rate", thigh, True, None), ("night_rate", tnight, False, 1),
                            ("night_etc_rate", tnight, True, 1)]
                for key, tc, etc, prio in variants:
                    if c.get(key) and (tc or key == "etc_rate"):
                        rows.append({**base, "time_class": tc, "user_class": b.electronic() if etc else None,
                                     "priority": prio, "amount": dec(c[key])})
        else:
            rows.append({"object": oid, "amount": dec(p["rate"])})
            if p.get("peak_rate") and p.get("rush"):
                rows.append({"object": oid, "time_class": rush_class(b, p["rush"]), "amount": dec(p["peak_rate"])})
            elif p.get("peak_rate"):
                tpeak = b.time_class("rush-hours", defined=False, label="Rush hours",
                                     note="The station charges more in rush hours; the hours aren't in the source table.")
                rows.append({"object": oid, "time_class": tpeak, "amount": dec(p["peak_rate"])})
                peak += 1
        if p.get("free_hours"):
            tfree = b.time_class("free", times=hours(p["free_hours"]), label="No charge")
            rows.append({"object": oid, "time_class": tfree, "priority": 2, "amount": "0"})
        kind = "congestion" if p.get("schedule") else "toll"
        by_window.setdefault((kind, p.get("valid_from") or "", p.get("valid_to") or ""), []).extend(rows)
        if p.get("group"):
            groups.setdefault((p["group"], p.get("group_minutes") or 60, p.get("group_pays") or "first"), []).append(oid)  # cost.go's defaults

    ids = {}
    for (kind, vf, vt), rows in sorted(by_window.items()):
        cid = ("congestion" if kind == "congestion" else "points") + (f"@{vf}..{vt}" if (vf or vt) else "")
        ch = {"id": cid, "type": "point", "component": "congestion" if kind == "congestion" else "unspecified",
              "unit": "passage", **clean({"valid_from": vf or None, "valid_to": vt or None})}
        if kind == "congestion":
            ch["unmatched"] = "free"
        b.charge(ch, rows)
        ids.setdefault(kind, []).append(cid)
    toll_ids = ids.get("toll", [])
    for (g, minutes, pays), objs in sorted(groups.items()):
        b.rule("passage_group", toll_ids, {"objects": objs, "minutes": minutes, "pays": pays})
    for oid, p in zip(oids, points):
        if p.get("within"):
            if p["within"] in systems:
                b.rule("included_in", toll_ids, {"charge": systems[p["within"]], "objects": [oid]})
            else:
                b.partial(oid, f"included in a system ({p['within']}) the table doesn't list")
    if peak:
        b.partial("rush-hours", f"{peak} toll points charge more in rush hours, whose hours aren't in the source table")
    if cong:
        cids = ids.get("congestion", [])
        _, high = congestion_days(b, t)
        if cong.get("day_cap") and cong.get("day_cap_high") and high:
            low_tc = b.time_class("outside-high-season", days=[{"exclude": {"date_ranges": high}}], label="Outside the high season")
            high_tc = b.time_class("congestion-high-season", days=[{"date_ranges": high}], label="High season")
            b.rule("cap", cids, {"per": "day", "amount": dec(cong["day_cap"]), "time_class": low_tc})
            b.rule("cap", cids, {"per": "day", "amount": dec(cong["day_cap_high"]), "time_class": high_tc})
        elif cong.get("day_cap"):
            b.rule("cap", cids, {"per": "day", "amount": dec(cong["day_cap"])})
        if cong.get("multi_pass_minutes"):
            b.rule("passage_group", cids, {"objects": sched_points, "minutes": cong["multi_pass_minutes"], "pays": "highest"})
        unknown = set(cong) - {"schedules", "day_cap", "day_cap_high", "multi_pass_minutes", "high_season", "july", "eve_taxed"}
        if unknown:
            b.keep("congestion", {k: cong[k] for k in sorted(unknown)}, f"congestion parameters {sorted(unknown)} aren't converted")


# Slovenia's nine emission columns as carbon-cost's Section.Amount picks them, in matching order:
# zero-emission first, then Euro VI by CO2 class, then older standards.
SI_COLUMNS = [({"co2_class": [5]}, "CO2 5", 8),
              ({"euro_class": ["6"], "co2_class": [2]}, "EURO VI CO2 2", 5),
              ({"euro_class": ["6"], "co2_class": [3]}, "EURO VI CO2 3", 6),
              ({"euro_class": ["6"], "co2_class": [4]}, "EURO VI CO2 4", 7),
              ({"euro_class": ["6"], "co2_class": [1]}, "EURO VI CO2 1", 4),
              ({"euro_class": ["EEV"]}, "EEV", 3),
              ({"euro_class": ["5"]}, "EURO V", 2),
              ({"euro_class": ["4"]}, "EURO IV", 1),
              ({"euro_class": ["0", "1", "2", "3"]}, "EURO 0-III", 0)]
SI_TOLL = [("R2", {"max": 2}), ("R3", {"min": 3, "max": 3}), ("R4", {"min": 4})]
SI_EMISSION = [("zev", {"co2_class": [5]})] + [(f"euro{n}", {"euro_class": [str(n)]}) for n in range(7)]


def convert_sections(b, secs, row_charges):
    method = secs.get("law", "") + (" " + secs["tariff_groups"] if secs.get("tariff_groups") else "")
    axle_cols = [("2 axles", {"max": 2}), ("3 axles", {"min": 3, "max": 3}), ("4+ axles", {"min": 4})]
    tariff_groups = {"E": [5], "A": [1, 2, 3, 4]}  # E for CO2 class 5, A for the rest
    at, si, tnight = None, None, None
    rows, rows_si = [], []
    # The km a trip drives on a section with its own toll pay the section's toll instead of the per-km
    # infrastructure rate; the other per-km components (air, noise, CO2) apply to them as to any km.
    secnet = None
    if row_charges:
        base = "roads"
        secnet = b.obj({"id": "own-toll-sections", "type": "network", "parents": [base],
                        "name": "Sections with a toll of their own (no per-km infrastructure charge on them)"})
        for cid in row_charges.get("infrastructure", []):
            ch = next(c for c in b.charges if c["id"] == cid)
            row = [None] * len(ch["columns"])
            row[ch["columns"].index("object")] = secnet
            row[ch["columns"].index("amount")] = "0"
            ch["rows"].append(row)
    for s in secs["list"]:
        parents = [secnet] if secnet else []
        if s.get("area"):
            parents.append(b.obj({"id": f"area:{s['area']}", "type": "network", "network": {"area": s["area"]}}))
        if s.get("tier"):
            parents.append(b.obj({"id": f"tier:{s['tier']}", "type": "network", "name": f"Sections of surcharge tier {s['tier']}"}))
        oid = b.obj({"id": "sec:" + s["id"], "type": "section", "parents": parents, "name": s["name"], "road": s["road"],
                     "from": place(s["from"]), "to": place(s["to"]), "length_km": s.get("km")})
        for g, cols in (s.get("tariff") or {}).items():
            at = at or b.class_set("sec-", [({"train_axles": ax, "co2_class": tariff_groups[gg]}, f"{gg} {lab}", None)
                                            for gg in ("E", "A") for lab, ax in axle_cols])
            for k, v in enumerate(cols):
                cid = at[(0 if g == "E" else 3) + k]
                rows.append({"object": oid, "vehicle_class": cid, "amount": dec(v)})
                if k == 2 and g in (s.get("night_kat4") or {}):
                    # carbon-cost: night-tariff sections between 22:00 and 05:00 (A 13 Brenner)
                    tnight = tnight or b.time_class("night-22-05", times=[["22:00", "05:00"]], label="Night")
                    rows.append({"object": oid, "vehicle_class": cid, "time_class": tnight, "amount": dec(s["night_kat4"][g])})
        if s.get("classes"):
            si = si or b.class_set("si-", [({"train_axles": ax, **crit}, f"{tc} {lab}", None)
                                           for tc, ax in SI_TOLL for crit, lab, _ in SI_COLUMNS])
            for ti, (tc, _) in enumerate(SI_TOLL):
                for ci, (_, _, col) in enumerate(SI_COLUMNS):
                    rows_si.append({"object": oid, "vehicle_class": si[ti * len(SI_COLUMNS) + ci], "amount": dec(s["classes"][tc][col])})
    if rows:
        b.charge({"id": "sections", "type": "section", "component": "infrastructure", "unit": "use", "method": method}, rows)
    if rows_si:
        b.charge({"id": "sections-si", "type": "section", "component": "infrastructure", "unit": "use", "method": method}, rows_si)
    for pk in secs.get("per_km", []):
        orct_comp, label = component(pk["component"])
        prow = []
        if pk["key"] == "class/emission/area":
            ids = b.class_set("si-km-", [({"train_axles": ax, **crit}, f"{tc} {e}", None) for tc, ax in SI_TOLL for e, crit in SI_EMISSION])
            lookup = {f"{tc}/{e}": ids[ti * len(SI_EMISSION) + ei] for ti, (tc, _) in enumerate(SI_TOLL) for ei, (e, _) in enumerate(SI_EMISSION)}
            for k, v in sorted(pk["rates"].items()):
                tc, e, area = k.split("/")
                prow.append({"object": b.obj({"id": f"area:{area}", "type": "network", "network": {"area": area}}),
                             "vehicle_class": lookup[f"{tc}/{e}"], "amount": dec(v)})
        elif pk["key"] == "class/tier":
            ids = b.class_set("si-tier-", [({"train_axles": ax}, tc, None) for tc, ax in SI_TOLL])
            for k, v in sorted(pk["rates"].items()):
                tc, tier = k.split("/")
                prow.append({"object": b.obj({"id": f"tier:{tier}", "type": "network", "name": f"Sections of surcharge tier {tier}"}),
                             "vehicle_class": ids[[x for x, _ in SI_TOLL].index(tc)], "amount": dec(v)})
        else:
            b.partial("dataset", f"per-km charge {pk['component']} uses an unknown key {pk['key']}")
            continue
        ch = {"id": "km-" + pk["component"], "name": pk.get("name", ""), "type": "section", "component": orct_comp,
              "unit": "km", "unmatched": "free", "method": pk.get("law", "")}
        if label:
            ch["component_label"] = label
        b.charge(ch, prow)
        missing = sum(1 for s in secs["list"] if not s.get("km"))
        if missing:
            b.partial(ch["id"], f"{missing} sections have no official length, so their per-km charge can't be priced")


# --- zones and fuel ----------------------------------------------------------------

def point_in_ring(pt, ring):
    x, y, inside = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def convert_zone(z, path):
    b = Builder(z, path)
    used = {"country", "currency", "valid_from", "valid_to", "name", "law", "sources", "min_kg", "charge",
            "exempt_euro", "euro_charges", "weekdays", "weekends", "no_charge", "polygons", "holes", "osm_extract"}
    polys = [[ring] for ring in z["polygons"]]
    for h in z.get("holes", []):
        for p in polys:
            if point_in_ring(h[0], p[0]):
                p.append(h)
                break
        else:
            b.partial("zone", "a hole of the zone lies in none of its polygons and was left out")
    b.obj({"id": "zone", "type": "area", "name": z["name"], "location": {"geometry": {"type": "MultiPolygon", "coordinates": polys}}})
    classes, amounts, top = [], [], z.get("exempt_euro") or 7
    if z.get("exempt_euro"):  # this standard or a later one pays nothing
        classes.append(({"euro_class": euro_list(range(z["exempt_euro"], 7), or_later=True)}, None, None))
        amounts.append("0")
    for e in sorted(z.get("euro_charges", []), key=lambda e: -e["min_euro"]):
        classes.append(({"euro_class": euro_list(range(e["min_euro"], top), or_later=top == 7)}, None, None))
        amounts.append(dec(e["charge"]))
        top = e["min_euro"]
    classes.append(({}, None, None))
    amounts.append(dec(z["charge"]))
    ids = b.class_set("zone-", classes)
    excl = {"date_ranges": [z["no_charge"]]} if z.get("no_charge") else None
    tcs = []
    if z.get("weekdays"):
        tcs.append(b.time_class("charging-weekdays", days=[clean({"weekdays": [1, 2, 3, 4, 5], "exclude": excl})], times=hours(z["weekdays"])))
    if z.get("weekends"):
        tcs.append(b.time_class("charging-weekends", days=[clean({"weekdays": [6, 7], "exclude": excl})], times=hours(z["weekends"])))
    if not tcs and excl:
        tcs.append(b.time_class("charging", days=[{"exclude": excl}]))
    rows = [{"vehicle_class": cid, "time_class": tc, "amount": a} for tc in (tcs or [None]) for cid, a in zip(ids, amounts)]
    ch = {"id": "zone-charge", "name": z["name"], "type": "area", "component": "access", "unit": "day", "objects": ["zone"]}
    if tcs:
        ch["unmatched"] = "free"
    b.charge(ch, rows)
    if z.get("osm_extract"):
        b.keep("osm_extract", z["osm_extract"])
    for k in sorted(set(z) - used):
        b.keep(k, z[k], f"{k} is kept as an extension (no ORCT field yet)")
    return b.doc({"description": "vehicles of at least the minimum mass", "criteria": clean({"train_mass_kg": rng(z.get("min_kg"))})})


def convert_fuel(f, path):
    b = Builder(f, path)
    used = {"country", "currency", "valid_from", "valid_to", "name", "law", "sources", "rate_per_t", "rate_per_l"}
    oid = b.obj({"id": "country", "type": "jurisdiction", "jurisdiction": {"country": f["country"]}})
    # A price per tonne of CO2, or a tax per litre of diesel.
    unit, rate = ("litre", f["rate_per_l"]) if "rate_per_l" in f else ("t_co2", f["rate_per_t"])
    b.charge({"id": "fuel-co2", "name": f["name"], "type": "quantity", "component": "carbon_price", "unit": unit,
              "objects": [oid]}, [{"amount": dec(rate)}])
    for k in sorted(set(f) - used):
        b.keep(k, f[k], f"{k} is kept as an extension (no ORCT field yet)")
    return b.doc({"description": "CO2 from fuel bought in the country", "criteria": {}})


def dumps(x, ind=0):
    """JSON with one object member per line, but short arrays of scalars (rows, coordinates)
    on one line, so tables stay readable and diffs small."""
    pad, inner = " " * ind, " " * (ind + 1)
    if isinstance(x, dict):
        if not x:
            return "{}"
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {dumps(v, ind + 1)}" for k, v in x.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(x, list):
        flat = json.dumps(x, ensure_ascii=False)
        if not any(isinstance(e, dict) for e in x) and len(flat) <= 160:
            return flat
        return "[\n" + ",\n".join(inner + dumps(e, ind + 1) for e in x) + "\n" + pad + "]"
    return json.dumps(x, ensure_ascii=False)


def is_day(s):
    try:
        return bool(s) and date.fromisoformat(s).isoformat() == s
    except ValueError:
        return False


def is_hours(h):
    return isinstance(h, list) and len(h) == 2 and all(isinstance(x, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x) for x in h)


def check(t, name):
    """The checks a table must pass before it is converted (what carbon-cost
    checked when it read the tables); a list of what is wrong."""
    bad = []
    if not is_day(t.get("valid_from")) or (t.get("valid_to") and not is_day(t["valid_to"])):
        bad.append("bad valid_from or valid_to")
    if not t.get("country") or not t.get("currency") or not t.get("sources"):
        bad.append("country, currency and sources are required")
    if t.get("valid_to") and is_day(t.get("valid_from")) and is_day(t["valid_to"]) and t["valid_to"] < t["valid_from"]:
        bad.append("valid_to before valid_from")
    if name.startswith("zone-"):
        if not re.fullmatch(rf"zone-{t.get('country', '').lower()}-[a-z0-9-]+-{t.get('valid_from')}\.json", name):
            bad.append("the name must be zone-<cc>-<zone>-<valid_from>.json")
        if not (t.get("name") and t.get("law") and t.get("charge", 0) > 0 and t.get("polygons") and t.get("osm_extract")):
            bad.append("name, law, charge, polygons and osm_extract are required")
        bad += [f"{k} must be [from, to] (HH:MM)" for k in ("weekdays", "weekends") if t.get(k) and not is_hours(t[k])]
        if t.get("no_charge") and len(t["no_charge"]) != 2:
            bad.append("no_charge must be [from, to] (MM-DD)")
        return bad
    if name.startswith("fuelco2-"):
        if name != f"fuelco2-{t.get('country', '').lower()}-{t.get('valid_from')}.json":
            bad.append("the name must be fuelco2-<cc>-<valid_from>.json")
        if not t.get("law") or ("rate_per_t" in t) == ("rate_per_l" in t) or t.get("rate_per_t", t.get("rate_per_l", -1)) < 0:
            bad.append("law and one of rate_per_t, rate_per_l are required")
        return bad
    if t.get("day", "") not in ("", "calendar", "24h"):
        bad.append(f"day must be calendar or 24h, not {t['day']!r}")
    if t.get("day") and not t.get("per_day"):
        bad.append("day is only for per_day tables")
    if any(not is_day(e.get("until")) for e in t.get("exemptions") or []):
        bad.append("bad exemption date")
    if t.get("region") and not t["region"].startswith(t.get("country", "") + "-"):
        bad.append(f"region {t['region']} is not in country {t.get('country')}")
    rows, systems, points = t.get("rows") or [], t.get("closed_systems") or [], t.get("toll_points") or []
    if not (rows or t.get("sections") or systems or points):
        bad.append("rows (or sections, toll systems or toll points) are required")
    if not 0 <= t.get("motorway_share", 0) <= 1:
        bad.append("motorway_share must be 0-1")
    if t.get("crossings") and (rows or not (systems or points)):
        bad.append("a crossings table has closed systems or toll points, and no rows")
    bad += [f"suburban_share[{k}] must be 0-1" for k, v in (t.get("suburban_share") or {}).items() if not 0 <= v <= 1]
    bad += [f"bad area {r['area']!r}" for r in rows if r.get("area", "") not in ("", "suburban", "interurban")]
    bad += [f"negative rate in {r}" for r in rows if r.get("rate", 0) < 0]
    bad += [f"vehicle_unit must be motor or trailer in {r}" for r in rows if r.get("vehicle_unit", "") not in ("", "motor", "trailer")]
    bad += [f"bad energy in {r}" for r in rows if set(r.get("energy") or []) - {"diesel", "petrol", "lpg", "cng", "lng", "electric", "hydrogen", "hybrid", "other"}]
    for sy in systems:
        if sy.get("free_hours") and not is_hours(sy["free_hours"]):
            bad.append(f"{sy['name']}: free_hours must be [from, to] (HH:MM)")
        if (sy.get("night_hours") or sy.get("night_prices")) and not (is_hours(sy.get("night_hours")) and sy.get("night_prices")):
            bad.append(f"{sy['name']}: night_hours must be [from, to] (HH:MM), with night_prices")
    names = {sy["name"] for sy in systems}
    schedules = (t.get("congestion") or {}).get("schedules", {})
    for p in points:
        if p.get("within") and p["within"] not in names:
            bad.append(f"toll point {p['name']}: no closed system {p['within']!r} in the table")
        bad += [f"toll point {p['name']}: {k} must be [from, to] (HH:MM)" for k in ("free_hours", "night_hours") if p.get(k) and not is_hours(p[k])]
        if any(p.get(k) and not is_day(p[k]) for k in ("valid_from", "valid_to")):
            bad.append(f"toll point {p['name']}: bad date")
        elif p.get("valid_from") and p.get("valid_to") and p["valid_to"] < p["valid_from"]:
            bad.append(f"toll point {p['name']}: valid_to before valid_from")
        if p.get("schedule") and p["schedule"] not in schedules:
            bad.append(f"toll point {p['name']}: no congestion schedule {p['schedule']!r} in the table")
    return bad


def write_index(out, commit=None):
    """index.json: every dataset under out, as written."""
    index = []
    for cc in sorted(os.listdir(out)):
        d = os.path.join(out, cc)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".orct.json"):
                continue
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                text = fh.read()
            doc = json.loads(text)
            ds = doc["dataset"]
            index.append({"id": ds["id"], "scheme": ds["scheme"]["id"], "country": ds["scheme"]["country"], "file": f"{cc}/{name}",
                          "name": ds["scheme"]["name"], "valid_from": ds["valid_from"], "valid_to": ds.get("valid_to"),
                          "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                          "coverage": "complete" if all(c["status"] == "complete" for c in doc["coverage"]) else "partial"})
    ids = [e["id"] for e in index]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise SystemExit(f"duplicate dataset ids: {dup}")
    head = {"orct": "0.3", "derived_from": {"url": REPO}}
    if commit:
        head["derived_from"]["commit"] = commit
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({**head, "datasets": index}, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return len(index)


def main():
    args = sys.argv[1:]
    commit = None
    if "--commit" in args:
        i = args.index("--commit")
        commit = args[i + 1]
        del args[i:i + 2]
    if args and args[0] == "--index":
        print(f"{write_index(args[1], commit)} datasets")
        return
    data, out = args
    n = 0
    for name in sorted(os.listdir(data)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(data, name)
        with open(path) as fh:
            t = json.load(fh)
        bad = check(t, name)
        if bad:
            raise SystemExit(f"{name}: " + "; ".join(bad))
        if name.startswith("zone-"):
            doc = convert_zone(t, path)
        elif name.startswith("fuelco2-"):
            doc = convert_fuel(t, path)
        else:
            doc = convert_table(t, path)
        cc = doc["dataset"]["scheme"]["country"].lower()
        os.makedirs(os.path.join(out, cc), exist_ok=True)
        with open(os.path.join(out, cc, f"{name[:-5]}.orct.json"), "w", encoding="utf-8") as fh:
            fh.write(dumps(doc) + "\n")
        n += 1
    print(f"{n} tables converted; {write_index(out, commit)} datasets in {out}")


if __name__ == "__main__":
    main()
