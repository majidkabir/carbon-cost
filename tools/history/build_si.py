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
columns. The sections' places and lengths come from the current table
(rates/data/si-2026-04-01.json, from the Uredba o cestninskih cestah in
cestnini annex); the 2024 section Brezovica–Vrhnika, split at Dragomer
from July 2025, joins its two halves. There's no external-cost charge
before April 2026.

Usage: python3 build_si.py fetched/ out-dir"""
import copy, datetime, html, json, os, re, sys

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
    cur = json.load(open(os.path.join(ROOT, "rates", "data", "si-2026-04-01.json"), encoding="utf-8"))
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


if __name__ == "__main__":
    main(*sys.argv[1:])
