"""Builds Slovenia's DarsGo toll tables from 1 January 2024 to 31 March
2026 from the official texts in PISRS (pisrs.si, the legal information
system of the Republic of Slovenia), fetched by the history workflow
(tools/history/sources.json, si-*):

- the section prices: the annex (Priloga) of each price list, Cenik
  cestnine za uporabo cestninskih cest, read by si_annex.py: Uradni list
  RS 14/18 as amended by 105/20 (NPB 3) and by 57/24 (NPB 4), then the
  price lists 47/25, 76/25 and 76/25 as amended by 102/25 (NPB 1);
- the surcharge for the Divača–Koper second rail track (Sklep o uvedbi
  pribitka k cestnini na določenih odsekih cestninskih cest, NPB 6 to 9):
  its art. 2 (tier a) and art. 3 (tier b) rates per km and sections;
- the Karavanke tunnel's toll per passage (Uredba o cestnini za uporabo
  cestnega predora Karavanke, art. 3);
- each act's date of application from the PISRS register data
  (veljaOd / uporabljaOd).

The prices before November 2025 have four EURO groups per class (E 0-3,
E4, E5, EEV/E6); the table keeps the current nine columns (EURO 0-III,
IV, V, EEV, VI with CO2 classes 1-5), EURO VI's price in all its CO2
columns. The sections' places and lengths come from the current table;
the 2024 section Brezovica–Vrhnika, split at Dragomer from July 2025,
joins its two halves. There's no external-cost charge before April 2026.

The current table, from 1 April 2026 (current()): the section prices from
the annex of the price list's NPB 3 (76/25, 102/25, 139/26 and 1771/26;
1771/26 only added the Serminska vpadnica to the port of Koper, from
26 October 2026, which isn't in the table); each section's official length
and suburban/interurban type from the annex of the Uredba o cestninskih
cestah in cestnini, NPB 2 (46/25, 102/25 and 129/26); the external-cost
charge per km from the Sklep 130/26 (in force 1 April 2026); the rail
surcharge from its NPB 9; the Karavanke toll from its Uredba (109/24 and
76/25). The sections' ends and display names are in
transcribed/si-places.json.

Usage: python3 build_si.py fetched/ out-dir"""
import copy, datetime, html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import si_annex  # noqa: E402

NPB = "https://pisrs.si/pregledNpb?idPredpisa=%s&idPredpisaChng=%s"
ACT = "https://pisrs.si/pregledPredpisa?id=%s"

CENIK = {  # source id: (title, URL for people)
    "si-cenik-npb3": ("Cenik cestnine za uporabo cestninskih cest (Uradni list RS, št. 14/18, 74/18, 85/20 in 105/20), NPB 3, with its annex", NPB % ("TARI209", "AKT_1165")),
    "si-cenik-npb4": ("Cenik cestnine za uporabo cestninskih cest (Uradni list RS, št. 14/18, 74/18, 85/20, 105/20 in 57/24), NPB 4, with its annex", NPB % ("TARI209", "ANJP30")),
    "si-cenik-47-25": ("Cenik cestnine za uporabo cestninskih cest (Uradni list RS, št. 47/25), with its annex", NPB % ("ANJP178", "ANJP178")),
    "si-cenik-76-25": ("Cenik cestnine za uporabo cestninskih cest (Uradni list RS, št. 76/25), with its annex", NPB % ("AKT_1550", "AKT_1550")),
    "si-cenik-76-25-npb1": ("Cenik cestnine za uporabo cestninskih cest (Uradni list RS, št. 76/25 in 102/25), NPB 1, with its annex", NPB % ("AKT_1550", "AKT_1561")),
}
PRIBITEK = {
    6: ("Sklep o uvedbi pribitka k cestnini na določenih odsekih cestninskih cest (Uradni list RS, št. 81/18 ... 118/23), NPB 6", NPB % ("SKLE11574", "SKLE13467")),
    7: ("Sklep o uvedbi pribitka k cestnini na določenih odsekih cestninskih cest (... 100/24), NPB 7", NPB % ("SKLE11574", "SKLE13808")),
    8: ("Sklep o uvedbi pribitka k cestnini na določenih odsekih cestninskih cest (... 46/25), NPB 8", NPB % ("SKLE11574", "SKLE14028")),
    9: ("Sklep o uvedbi pribitka k cestnini na določenih odsekih cestninskih cest (... 76/25), NPB 9", NPB % ("SKLE11574", "SKLE14128")),
}
KARAVANKE = {
    "si-karavanke-14-18-npb6": ("Uredba o cestnini za uporabo cestnega predora Karavanke (Uradni list RS, št. 14/18 ... 132/23), NPB 6, art. 3", NPB % ("URED7728", "URED8997")),
    "si-karavanke-14-18-npb7": ("Uredba o cestnini za uporabo cestnega predora Karavanke (Uradni list RS, št. 14/18 ... 53/24), NPB 7, art. 3", NPB % ("URED7728", "URED9145")),
    "si-karavanke-109-24-npb0": ("Uredba o cestnini za uporabo cestnega predora Karavanke (Uradni list RS, št. 109/24), art. 3", ACT % "URED9295"),
}
# Each table: from (checked against the register's date of the act that
# starts it), the price list, the surcharge version, the Karavanke version.
PERIODS = [
    ("2024-01-01", "si-cenik-npb3", 6, "si-karavanke-14-18-npb6", ("si-zbirka-skle13467",)),
    ("2024-07-15", "si-cenik-npb4", 6, "si-karavanke-14-18-npb7", ("si-zbirka-anjp30", "si-zbirka-ured9145")),
    ("2025-01-01", "si-cenik-npb4", 7, "si-karavanke-109-24-npb0", ("si-zbirka-skle13808", "si-zbirka-ured9295")),
    ("2025-07-01", "si-cenik-47-25", 8, "si-karavanke-109-24-npb0", ("si-zbirka-anjp178", "si-zbirka-skle14028")),
    ("2025-11-01", "si-cenik-76-25", 8, "si-karavanke-109-24-npb0", ("si-zbirka-akt-1550",)),
    ("2026-01-01", "si-cenik-76-25-npb1", 9, "si-karavanke-109-24-npb0", ("si-zbirka-akt-1561", "si-zbirka-skle14128")),
]
END = "2026-03-31"  # the day before the current table (139/26 and the external-cost charge, 1 April 2026)


def key(name):
    """A section name compared without case, spaces or dashes (Sermin is
    spelled Srmin since 2025; text after a footnote mark isn't the name)."""
    n = name.split("")[0].upper().replace("SERMIN", "SRMIN")
    return re.sub(r"[\s\-–—]", "", n)


def text(path):
    d = json.load(open(path, encoding="utf-8"))["data"]["besedilo"]
    return re.sub(r"\s+", " ", " \n ".join(html.unescape(re.sub(r"<[^>]+>", " ", x.get("vsebina") or "")) for x in d))


def applies(path):
    e = json.load(open(path, encoding="utf-8"))["data"]["evidencniPodatki"]
    return e.get("uporabljaOd") or e.get("veljaOd")


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def pribitek(fetched, n):
    t = text(os.path.join(fetched, f"si-pribitek-npb{n}.json"))
    out = {}
    for art, tier in (("2. člen", "a"), ("3. člen", "b")):
        i = t.index(art)
        part = t[i:t.index("člen", i + len(art) + 1)]
        m = re.search(r"\(R2\) (0, ?\d+) eura.*\(R3\) (0, ?\d+) eura.*\(R4\) (0, ?\d+) eura", part)
        names = re.findall(r"\b(?:A\d|H\d)\s+(.+?)(?=\s+(?:A\d|H\d)\s|\s+\d+\. člen|$)", part[part.index("Cestninski odsek") + 16:])
        names = [re.sub(r"\s+\d+\.$", "", x.strip()) for x in names]  # the next article's number
        out[tier] = {"rates": dict(zip(("R2", "R3", "R4"), map(num, m.groups()))), "sections": {key(x) for x in names}}
    return out


def karavanke(fetched, sid):
    t = text(os.path.join(fetched, sid + ".json"))
    i = t.index("3. člen")
    m = re.search(r"R2 (\d+,\d+) eura, za vozila cestninskega razreda R3 (\d+,\d+) eura in za vozila cestninskega razreda R4 (\d+,\d+) eura", t[i:])
    return dict(zip(("R2", "R3", "R4"), map(num, m.groups())))


def main(fetched, out):
    cur = current(fetched, out)
    geo = {key(s["name"]): s for s in cur["sections"]["list"] if s["id"] != "karavanke"}
    kv0 = next(s for s in cur["sections"]["list"] if s["id"] == "karavanke")
    rail0 = next(p for p in cur["sections"]["per_km"] if p["component"] == "rail_surcharge")
    # The 2024 section Brezovica–Vrhnika: its two later halves joined.
    a, b = geo[key("Brezovica–Dragomer")], geo[key("Dragomer–Vrhnika")]
    geo[key("Brezovica–Vrhnika")] = dict(a, id="a1-brezovica-vrhnika", name="Brezovica–Vrhnika", to=b["to"], km=round(a["km"] + b["km"], 3))
    rows = {sid: si_annex.rows(os.path.join(fetched, sid + "-priloga.pdf")) for sid in CENIK}
    # 76/25's annex wraps its names past reading: its rows are 102/25's, priced alike.
    # (Row by row where the prices agree; the Koper sections 102/25 measured anew keep their own names.)
    later = rows["si-cenik-76-25-npb1"]
    rows["si-cenik-76-25"] = [(r[0], later[i][1] if i < len(later) and later[i][2] == r[2] else r[1], r[2]) for i, r in enumerate(rows["si-cenik-76-25"])]
    os.makedirs(out, exist_ok=True)
    for k, (start, cid, pn, kid, acts) in enumerate(PERIODS):
        for a_ in acts or ():
            d = applies(os.path.join(fetched, a_ + ".json"))
            if d != start:
                sys.exit(f"{start}: {a_} applies from {d}")
        end = END if k == len(PERIODS) - 1 else (datetime.date.fromisoformat(PERIODS[k + 1][0]) - datetime.timedelta(days=1)).isoformat()
        rail = pribitek(fetched, pn)
        kv = karavanke(fetched, kid)
        secs = []
        for road, name, prices in rows[cid]:
            g = geo.get(key(name))
            if g is None:
                sys.exit(f"{cid}: {road} {name}: no such section in si-2026-04-01.json")
            s = copy.deepcopy(g)
            s["road"] = road
            s.pop("area", None)  # suburban/interurban counts for the external-cost charge only (April 2026)
            s.pop("tier", None)
            for tier, v in rail.items():
                if key(name) in v["sections"]:
                    s["tier"] = tier
            s["classes"] = {c: (p if len(p) == 9 else p[:3] + [p[3]] * 6) for c, p in prices.items()}
            secs.append(s)
        found = {t: sum(1 for s in secs if s.get("tier") == t) for t in rail}
        for t, v in rail.items():
            if found[t] != len(v["sections"]):
                sys.exit(f"{start}: rail tier {t}: {found[t]} sections priced, the Sklep lists {len(v['sections'])}")
        kvs = dict(copy.deepcopy(kv0), classes={c: [v] * 9 for c, v in kv.items()})
        ctitle, curl = CENIK[cid]
        ptitle, purl = PRIBITEK[pn]
        ktitle, kurl = KARAVANKE[kid]
        tb = {
            "country": "SI", "currency": "EUR", "valid_from": start, "valid_to": end or "",
            "name": cur["name"],
            "law": f"{ctitle}: infrastructure charge per toll section, toll class and EURO class, in euros excluding VAT (22% VAT is charged on the toll); {ptitle}, art. 2 and 3; {ktitle}. Read from PISRS (pisrs.si); each act's date of application from its register data. Section places and lengths as in the 2026 table (Uredba o cestninskih cestah in cestnini, Annex).",
            "sources": [{"title": ctitle, "url": curl}, {"title": ptitle, "url": purl}, {"title": ktitle, "url": kurl}],
            "vehicles": cur["vehicles"], "min_kg": cur["min_kg"],
            "tolled_roads": f"The DARS motorway and expressway network, {len(secs)} toll sections; a section is charged when the route passes both of its ends. The Karavanke tunnel's Slovenian toll is a fixed amount per passage ({ktitle}: R2 {kv['R2']:.2f}, R3 {kv['R3']:.2f}, R4 {kv['R4']:.2f} EUR excluding VAT).",
            "rows": [],
            "sections": {
                "law": f"{ctitle}" + ("; columns EURO 0-III, IV, V, EEV/VI as the price list gives them, EURO VI's price in all its CO2 columns" if cid in ("si-cenik-npb3", "si-cenik-npb4", "si-cenik-47-25") else ""),
                "tariff_groups": cur["sections"]["tariff_groups"],
                "list": [kvs] + secs,
                "per_km": [dict(copy.deepcopy(rail0), law=f"{ptitle}, art. 2 (a) and 3 (b): EUR per km of the section's length, to 31 December 2052",
                                rates={f"{c}/{t}": v["rates"][c] for t, v in rail.items() for c in ("R2", "R3", "R4")})],
            },
        }
        if not tb["valid_to"]:
            del tb["valid_to"]
        for f in ("osm_extract",):
            if f in cur:
                tb[f] = cur[f]
        path = os.path.join(out, f"si-{start}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(secs), "sections", "rail", {t: v["rates"]["R4"] for t, v in rail.items()}, "karavanke", kv)



AREA = {"Medmestna": "interurban", "Primestna": "suburban"}
EM = {"Euro 0": "euro0", "Euro I": "euro1", "Euro II": "euro2", "Euro III": "euro3", "Euro IV": "euro4",
      "Euro V": "euro5", "Euro VI": "euro6", "Brezemisijska vozila": "zev"}


def loose(name):
    """A section name as the price list's annex reads it, for comparing:
    letters only, no diacritics (its font loses Č)."""
    n = key(name)
    for a, b in ("ČC", "ŠS", "ŽZ", "ĆC", "ĐD"):
        n = n.replace(a, b)
    return re.sub(r"[^A-Z0-9]", "", n)


def uredba_sections(fetched, sid="si-uredba-9382-npb2-priloga"):
    """[(road, name, km, area)] from the Uredba's annex, in its order."""
    t = subprocess.run(["pdftotext", "-layout", os.path.join(fetched, sid + ".pdf"), "-"], capture_output=True, text=True, check=True).stdout
    out = []
    for line in t.splitlines():
        m = re.match(r"^\s*(A\d|H\d|[RG]\d-\d+)\s+(.+?)\s+(\d+,\d{3}) (Medmestna|Primestna) cesta\s*$", line)
        if m:
            out.append((m.group(1), m.group(2), num(m.group(3)), AREA[m.group(4)]))
    return out


def external_costs(fetched):
    """Sklep 130/26, art. 2: EUR per km by toll class and EURO class,
    suburban then interurban."""
    t = text(os.path.join(fetched, "si-sklep-14332.json"))
    assert "Ta sklep začne veljati 1. aprila 2026." in t
    part = t[t.index("2. člen"):t.index("3. člen")]
    rates = {}
    heads = [("R2", "Vozila prvega cestninskega razreda (R2)"), ("R3", "Vozila drugega cestninskega razreda (R3)"), ("R4", "Vozila tretjega cestninskega razreda (R4)")]
    for k, (cls, head) in enumerate(heads):
        seg = part[part.index(head) + len(head):part.index(heads[k + 1][1]) if k + 1 < len(heads) else len(part)]
        got = re.findall(r"(Euro (?:0|I|II|III|IV|V|VI)|Brezemisijska vozila) (\d+,\d+) (\d+,\d+)", seg)
        assert [g[0] for g in got] == list(EM), got
        for name, sub, inter in got:
            rates[f"{cls}/{EM[name]}/suburban"] = num(sub)
            rates[f"{cls}/{EM[name]}/interurban"] = num(inter)
    return rates


# The acts the current table reads, as PISRS's register gives their
# amendments (citat). None has an end date: the table runs until one of
# them changes. 1746/26 added the Serminska vpadnica (the table from 26
# October 2026).
IN_FORCE = {
    "si-zbirka-akt-1550": "76/25, 102/25, 139/26 in 1771/26",  # Cenik cestnine
    "si-zbirka-ured9382": "46/25, 102/25, 129/26 in 1746/26",  # Uredba o cestninskih cestah in cestnini
    "si-zbirka-skle14332": "130/26",  # Sklep o pristojbini za zunanje stroške
    "si-zbirka-skle11574": "81/18, 4/20, 105/20, 70/21, 60/22, 155/22, 118/23, 100/24, 46/25 in 76/25",  # Sklep o uvedbi pribitka
    "si-zbirka-ured9295": "109/24 in 76/25",  # Uredba o cestnini za predor Karavanke
}


def until(fetched, start):
    """The current table's last day: none while every act it reads is in
    force with no end date (veljaDo, uporabljaDo) and no amendment past
    those read; else the day before the first change, with a warning."""
    ends = []
    for sid, citat in IN_FORCE.items():
        d = json.load(open(os.path.join(fetched, sid + ".json"), encoding="utf-8"))["data"]
        e = d["evidencniPodatki"]
        got = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", e["citat"]))).strip()
        for k in ("veljaDo", "uporabljaDo"):
            if e.get(k):
                ends.append((e[k], f"{sid}: {k} {e[k]}"))
        if got != "Uradni list RS, št. " + citat:
            # A later amendment: its consolidated text's first day, as PISRS gives it.
            later = [v["datumZacetkaUporabe"] for v in (d.get("besedilo") or {}).get("npbVerzije") or [] if (v.get("datumZacetkaUporabe") or "") > start]
            if not later:
                sys.exit(f"{sid}: amended ({got}), and no date for it: read the amendment")
            last = (datetime.date.fromisoformat(max(later)) - datetime.timedelta(days=1)).isoformat()
            ends.append((last, f"{sid}: {got}"))
    if not ends:
        return None
    last, why = min(ends)
    print(f"::warning title=build_si::the table ends on {last} ({why}); read the change")
    return last


def current(fetched, out):
    """The table from 1 April 2026."""
    start = applies(os.path.join(fetched, "si-zbirka-skle14332.json"))
    assert start == "2026-04-01", start
    places = json.load(open(os.path.join(HERE, "transcribed", "si-places.json"), encoding="utf-8"))["sections"]
    # G2-114 (the Serminska vpadnica) is priced from 26 October 2026: october().
    kv0, places = places[0], [p for p in places[1:] if p["id"] != "g2-114"]
    assert kv0["id"] == "karavanke"
    u = uredba_sections(fetched)
    assert "(Uradni list RS, št. 129/26 z dne 27. 3. 2026)" in text(os.path.join(fetched, "si-uredba-9382-npb2.json"))
    ctext = text(os.path.join(fetched, "si-cenik-76-25-npb3.json"))
    for want in ("(Uradni list RS, št. 139/26 z dne 30. 3. 2026)", "(Uradni list RS, št. 1771/26 z dne 23. 10. 2026)"):
        assert want in ctext, want
    dop = text(os.path.join(fetched, "si-cenik-dopolnitev-1771-26.json"))
    prices = si_annex.rows(os.path.join(fetched, "si-cenik-76-25-npb3-priloga.pdf"))
    # 1771/26 added the one section the Uredba's annex doesn't list.
    extra = [r for r in prices if r[0] == "G2-114"]
    assert len(extra) == 1 and "VPADNICA" in key(extra[0][1]), extra
    # 1771/26: one article adding the G2-114 row to each class's table, from 26 October 2026.
    added = re.findall(r"doda nova vrstica, ki se glasi: » G2-114 SERMINSKA VPADNICA-PRIKLJ\. LUKA KOPER ((?:\d+,\d+ ?){9}) «", dop)
    assert dop.count("doda nova vrstica") == 3 and len(added) == 3, "1771/26 isn't the Serminska vpadnica's addition"
    assert [[num(x) for x in a.split()] for a in added] == [extra[0][2][k] for k in ("R2", "R3", "R4")]
    assert "2. člen (začetek veljavnosti) Ta dopolnitev cenika začne veljati 26. oktobra 2026." in dop and "3. člen" not in dop
    prices = [r for r in prices if r[0] != "G2-114"]
    assert len(prices) == len(u) == len(places), (len(prices), len(u), len(places))
    rail = pribitek(fetched, 9)
    secs = []
    for (road, name, km, area), (proad, pname, cls), pl in zip(u, prices, places):
        a, b = loose(name), loose(pname)
        assert road == proad and (a == b or a.startswith(b) or a.endswith(b) or b.startswith(a)), (road, name, proad, pname)
        assert key(pl["name"]) == key(name), (pl["name"], name)
        s = {"id": pl["id"], "road": road, "name": pl["name"], "from": pl["from"], "to": pl["to"], "km": km, "area": area, "classes": cls}
        for tier, v in rail.items():
            if key(name) in v["sections"]:
                s["tier"] = tier
        secs.append(s)
    for t, v in rail.items():
        n = sum(1 for s in secs if s.get("tier") == t)
        assert n == len(v["sections"]), (t, n, len(v["sections"]))
    kt = text(os.path.join(fetched, "si-karavanke-109-24-npb1.json"))
    assert "(Uradni list RS, št. 76/25 z dne 3. 10. 2025)" in kt
    kv = karavanke(fetched, "si-karavanke-109-24-npb1")
    kvs = {"id": "karavanke", "road": kv0["road"], "name": kv0["name"], "from": kv0["from"], "to": kv0["to"], "classes": {c: [v] * 9 for c, v in kv.items()}}
    ktitle = "Uredba o cestnini za uporabo cestnega predora Karavanke (Uradni list RS, št. 109/24 in 76/25), art. 3"
    tb = {
        "country": "SI", "currency": "EUR", "valid_from": start,
        "name": "Slovenian distance toll (DarsGo)",
        "law": "Cenik cestnine za uporabo cestninskih cest (Uradni list RS, št. 76/25, 102/25, 139/26 in 1771/26), Annex: infrastructure charge per toll section, toll class and EURO / CO2 class, in euros excluding VAT (22% VAT is charged on the toll). "
               "The cenik, the Uredba o cestninskih cestah in cestnini, the sklep on external costs and the Karavanke uredba have no end date (PISRS's register): the table runs until one of them is amended.",
        "sources": [{"title": "Cenik cestnine za uporabo cestninskih cest, consolidated text NPB 3 (26 October 2026), with its annex of section prices", "url": NPB % ("AKT_1550", "ANJP333")},
                    {"title": "Uredba o cestninskih cestah in cestnini (Uradni list RS, št. 46/25, 102/25 in 129/26), NPB 2, Annex: toll sections, their lengths and suburban/interurban type", "url": ACT % "URED9382"},
                    {"title": "Sklep o določitvi višine pristojbine za zunanje stroške (Uradni list RS, št. 130/26), in force 1 April 2026", "url": ACT % "SKLE14332"},
                    {"title": "Sklep o uvedbi pribitka k cestnini na določenih odsekih cestninskih cest, consolidated text NPB 9 (6 October 2025)", "url": NPB % ("SKLE11574", "SKLE14128")},
                    {"title": ktitle, "url": ACT % "URED9295"}],
        "vehicles": "Motor vehicles over 3.5 t technically permissible maximum mass: R2 two axles, R3 three, R4 more than three",
        "min_kg": 3501,
        "tolled_roads": f"The DARS motorway and expressway network, {len(secs) + 1} toll sections; a section is charged when the route passes both of its ends. Not included: the Serminska vpadnica to the port of Koper, priced from 26 October 2026 (Uradni list RS, št. 1771/26). The Karavanke tunnel's Slovenian toll is a fixed amount per passage (Uredba o cestnini za uporabo cestnega predora Karavanke, Uradni list RS, št. 109/24 in 76/25, art. 3: R2 {kv['R2']:.2f}, R3 {kv['R3']:.2f}, R4 {kv['R4']:.2f} EUR excluding VAT).",
        "rows": [],
        "sections": {
            "law": "Cenik cestnine za uporabo cestninskih cest, Annex (as amended by Uradni list RS, št. 139/26, from 1 April 2026)",
            "tariff_groups": "Toll classes R2 (2 axles), R3 (3), R4 (more than 3); columns EURO 0-III, IV, V, EEV, VI with CO2 class 1, then EURO VI with CO2 classes 2-5. EEV is priced as EURO V here.",
            "list": [kvs] + secs,
            "per_km": [
                {"component": "air_noise", "name": "External-cost charge (air pollution and noise)",
                 "law": "Sklep o določitvi višine pristojbine za zunanje stroške za posamezne razrede vozil nad 3.500 kg NDM (Uradni list RS, št. 130/26), art. 2: EUR per km of the section's length by toll class and EURO class, suburban or interurban section (Uredba o cestninskih cestah in cestnini, Annex)",
                 "key": "class/emission/area", "rates": external_costs(fetched)},
                {"component": "rail_surcharge", "name": "Surcharge for the Divača-Koper second rail track",
                 "law": "Sklep o uvedbi pribitka k cestnini na določenih odsekih cestninskih cest (NPB 9), art. 2 (a) and 3 (b): EUR per km of the section's length, to 31 December 2052",
                 "key": "class/tier", "rates": {f"{c}/{t}": v["rates"][c] for t, v in rail.items() for c in ("R2", "R3", "R4")}},
            ],
        },
    }
    # 1771/26 (and the Uredba's 1746/26) from 26 October 2026: the table
    # ends the day before, and the next adds the Serminska vpadnica.
    tb["valid_to"] = "2026-10-25"
    tb["tolled_roads"] = tb["tolled_roads"].replace("Not included: the Serminska vpadnica to the port of Koper, priced from 26 October 2026 (Uradni list RS, št. 1771/26).", "The Serminska vpadnica to the port of Koper is priced from 26 October 2026 (Uradni list RS, št. 1771/26: the next table).")
    tb["law"] = tb["law"].split(" The cenik, the Uredba")[0]
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"si-{start}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(secs), "sections")
    october(fetched, out, tb, extra[0], kv)
    return tb


def october(fetched, out, april, extra, kv):
    """From 26 October 2026: the April table and the Serminska vpadnica
    (G2-114) to the port of Koper, its length and type from the Uredba's
    annex as 1746/26 completed it (NPB 3), its prices from the cenik as
    1771/26 completed it, its ends where OpenStreetMap has the tolled road
    (transcribed/si-places.json)."""
    start = "2026-10-26"
    npb = [v for v in json.load(open(os.path.join(fetched, "si-zbirka-ured9382.json"), encoding="utf-8"))["data"]["besedilo"]["npbVerzije"] if v["naziv"] == "NPB 3"]
    assert len(npb) == 1 and npb[0]["datumZacetkaUporabe"] == start, npb
    assert "Uredbo o dopolnitvi Uredbe o cestninskih cestah in cestnini (Uradni list RS, št. 1746/26" in text(os.path.join(fetched, "si-uredba-9382-npb3.json"))
    u2, u3 = uredba_sections(fetched), uredba_sections(fetched, "si-uredba-9382-npb3-priloga")
    assert u3[:-1] == u2 and u3[-1][0] == "G2-114", u3[-1]
    road, _, km, area = u3[-1]
    pl = [s for s in json.load(open(os.path.join(HERE, "transcribed", "si-places.json"), encoding="utf-8"))["sections"] if s["id"] == "g2-114"]
    assert len(pl) == 1, pl
    s = {"id": "g2-114", "road": road, "name": pl[0]["name"], "from": pl[0]["from"], "to": pl[0]["to"], "km": km, "area": area, "classes": extra[2]}
    tb = copy.deepcopy(april)
    tb["valid_from"] = start
    del tb["valid_to"]
    tb["sections"]["list"].append(s)
    n = len(tb["sections"]["list"])
    tb["law"] = (tb["law"] + " The cenik, the Uredba o cestninskih cestah in cestnini, the sklep on external costs and the Karavanke uredba have no end date (PISRS's register): the table runs until one of them is amended.")
    tb["sections"]["law"] = "Cenik cestnine za uporabo cestninskih cest, Annex (as amended by Uradni list RS, št. 139/26, from 1 April 2026, and completed by 1771/26 with the Serminska vpadnica, from 26 October 2026)"
    tb["tolled_roads"] = (f"The DARS motorway and expressway network and the Serminska vpadnica (G2-114) to the port of Koper, {n} toll sections; a section is charged when the route passes both of its ends. "
                          f"The Karavanke tunnel's Slovenian toll is a fixed amount per passage (Uredba o cestnini za uporabo cestnega predora Karavanke, Uradni list RS, št. 109/24 in 76/25, art. 3: R2 {kv['R2']:.2f}, R3 {kv['R3']:.2f}, R4 {kv['R4']:.2f} EUR excluding VAT).")
    for src in tb["sources"]:
        if src["url"] == ACT % "URED9382":
            src["title"] = "Uredba o cestninskih cestah in cestnini (Uradni list RS, št. 46/25, 102/25, 129/26 in 1746/26), NPB 3, Annex: toll sections, their lengths and suburban/interurban type"
    tb["sources"].append({"title": "OpenStreetMap: the Serminska vpadnica's tolled way (way 498569140, toll:hgv=yes from 26 October 2026)", "url": "https://www.openstreetmap.org/way/498569140"})
    last = until(fetched, start)
    if last:
        tb["valid_to"] = last
    path = os.path.join(out, f"si-{start}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, n, "sections")


if __name__ == "__main__":
    main(*sys.argv[1:])
