"""Builds the historical tables of the Eurovignette countries and of
Denmark's km toll in 2025, from the texts the History data workflow
fetched (tools/history/sources.json).

Usage: python3 build_eurovignette.py fetched/ out-dir

- Sweden, 2024 and 2025: the vägavgift amounts in kronor of Förordning
  (2023:599) for 2024, (2024:953) for 2025 as first issued (EURO class
  only, 138 kronor a day for all), and (2025:46), its amendment by CO2
  class in force from 25 March 2025 (the protocol's new tariff structure).
  The last number of each row is the day's amount.
- Luxembourg, until 24 March 2025: RGD du 21 mai 2019 as published, art.
  1er 4°: 12 euros a day for every vehicle from 1 July 2019.
- Netherlands, until 30 June 2026: the Wet belasting zware
  motorrijtuigen, art. 10: before 25 March 2025 the day's tariff for
  every vehicle; from 25 March 2025 the day's table by CO2 class, EURO
  class and axles, as corrected with retroactive effect by Stb. 2025,
  445 (the protocol's amounts prevail). The law lapsed when the
  vrachtwagenheffing started on 1 July 2026.
- Denmark, until 31 December 2024: lov om afgift af vejbenyttelse (LBK
  nr. 174 af 24/02/2020) § 3, stk. 4, nr. 5: 89 kroner a day for foreign
  trucks; § 4 adjusts the amounts only on a change of 5% or more in the
  krone's euro value, which the pegged krone hasn't seen. The law ended
  on 1 January 2025.
- Denmark, 2025: lov om vejafgift § 5 as worded by lov nr. 1489 af
  10/12/2024, in force 1 January 2025: the rates and their components
  equal those of rates/data/dk-2026-01-01.json, which is checked against
  the rates, the environmental zone surcharges and the CO2 component in
  Transportministeriet's report of 25 March 2025 (tables 1-3).
"""
import html, json, os, re, sys

EURO = {"0": [0], "I": [1], "II": [2], "III": [3], "IV": [4], "V": [5], "VI": [6]}
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def save(out, tb):
    os.makedirs(out, exist_ok=True)
    name = tb.pop("_file")
    path = os.path.join(out, name)
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(tb["rows"]), "rows")


def se_rows(txt):
    """The day's amounts of a vägavgift förordning: by EURO class only
    (before 25 March 2025) or by CO2 class and, in class 1, EURO class."""
    rows = []
    i3, i4 = txt.index("Högst 3 axlar"), txt.index("Minst 4 axlar")
    for block, axles in ((txt[i3:i4], {"max_axles": 3}), (txt[i4:], {"min_axles": 4})):
        co2, euro = [], []
        for line in block.splitlines():
            tok = line.replace("eller renare", "").split()
            if not tok or not re.fullmatch(r"\d+", tok[-1]):
                continue
            day = int(tok[-1])
            if tok[0] == "1" and len(tok) > 1 and tok[1] == "0":
                euro.append(([0], day))
            elif tok[0] in EURO and len(tok) >= 5:
                euro.append((EURO[tok[0]], day))
            elif tok[0] in ("2", "3", "4", "5") and len(tok) > 2:
                co2.append((int(tok[0]), day))
        if len(euro) != 7 or len(co2) not in (0, 4):
            sys.exit(f"vägavgift: {len(euro)} EURO rows, {len(co2)} CO2 rows")
        for c, day in co2:
            rows.append({"component": "toll", "min_kg": 12000, **axles, "co2_class": [c], "rate": day})
        for e, day in euro:
            r = {"component": "toll", "min_kg": 12000, **axles, "euro": e, "rate": day}
            if co2:
                r["co2_class"] = [1]
            rows.append(r)
    rows.sort(key=lambda r: "euro" in r)
    return rows


def sweden(fetched, out):
    base = {
        "country": "SE", "currency": "SEK",
        "name": "Swedish road charge for heavy goods vehicles (vägavgift, Eurovignette)",
        "vehicles": "Trucks and articulated combinations of 12 t or more total weight, for goods transport",
        "min_kg": 12000,
        "tolled_roads": "Motorways and the roads in annex 1 of the law (for foreign vehicles; Swedish vehicles pay for all roads, yearly).",
        "per_day": True, "day": "calendar",
    }
    law_src = {"title": "Lag (1997:1137), consolidated (Riksdagen)", "url": "https://data.riksdagen.se/dokument/sfs-1997-1137.text"}
    for sfs, url, frm, to, what in (
        ("2023:599", "https://svenskforfattningssamling.se/sites/default/files/sfs/2023-10/SFS2023-599.pdf", "2024-01-01", "2024-12-31",
         "amounts in kronor for 2024 from Förordning (2023:599): per calendar day, week, month or year for trucks and combinations of 12 t or more, by axles (at most 3, at least 4) and EURO class; the day's amount is 138 kronor for all"),
        ("2024:953", "https://www.svenskforfattningssamling.se/sites/default/files/sfs/2024-10/SFS2024-953.pdf", "2025-01-01", "2025-03-24",
         "amounts in kronor for 2025 from Förordning (2024:953) as first issued: per calendar day, week, month or year by axles and EURO class; the day's amount is 138 kronor for all. Its amendment SFS 2025:46 applies from 25 March 2025"),
        ("2025:46", "https://svenskforfattningssamling.se/sites/default/files/sfs/2025-02/SFS2025-46.pdf", "2025-03-25", "2025-12-31",
         "amounts in kronor for 2025 from Förordning (2024:953) as amended by SFS 2025:46 (in force 25 March 2025, under the transitional provisions of SFS 2024:292): per calendar day, week, month or year by axles (at most 3, at least 4), CO2 emission class and, in CO2 class 1, EURO class"),
    ):
        txt = open(os.path.join(fetched, f"se-sfs-{sfs.replace(':', '-')}.txt"), encoding="utf-8").read()
        rows = se_rows(txt)
        save(out, {**base, "_file": f"se-{frm}.json", "valid_from": frm, "valid_to": to,
                   "law": f"Lag (1997:1137) om vägavgift för vissa tunga fordon, 5, 10, 11 and 23 §§; {what}. A foreign truck pays per day of use; a Swedish one pays yearly. The table keeps the daily amount. Not subject to VAT.",
                   "sources": [{"title": f"SFS {sfs} (Svensk författningssamling)", "url": url}, law_src],
                   "rows": rows})


def cells(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<(td|th|p|div|tr|br|li|h\d)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("​", "").replace("‎", "").replace("\xa0", " ")
    return [re.sub(r"\s+", " ", c).strip() for c in t.split("\n") if c.strip()]


def flat_day(eur, axles_all=True):
    return [{"component": "toll", "min_kg": 12000, "rate": eur}]


def luxembourg(fetched, out):
    c = cells(os.path.join(fetched, "lu-rgd-2019-jo.html"))
    s = next(x for x in c if x.startswith("4° Le droit d’usage journalier"))
    m = re.search(r"à (\d+) euros à partir du 1er juillet 2019", s)
    assert m, s
    save(out, {
        "_file": "lu-2019-07-01.json", "country": "LU", "currency": "EUR", "valid_from": "2019-07-01", "valid_to": "2025-03-24",
        "name": "Luxembourg road user charge (Eurovignette, droit d'usage)",
        "law": f"Loi modifiée du 24 février 1995 (Eurovignette Agreement of 9 February 1994); Règlement grand-ducal du 21 mai 2019, art. 1er, 4° as published: the daily charge, administrative costs included, is {m.group(1)} euros for every category of vehicle from 1 July 2019, for goods vehicles of 12 t or more. Replaced on 25 March 2025 by the amounts by CO2 class (RGD of 18 December 2024).",
        "sources": [{"title": "RGD du 21 mai 2019, as published (Legilux, Mémorial A 353)", "url": "https://legilux.public.lu/eli/etat/leg/rgd/2019/05/21/a353/jo"},
                    {"title": "Guichet.lu: Eurovignette, droit d'usage routier pour poids-lourds (a day's charge is a calendar day, 00:00 to 24:00)", "url": "https://guichet.public.lu/fr/entreprises/import-export/transit/transit-ue/e-vignette-poids-lourds.html"}],
        "vehicles": "Goods vehicles of 12 t or more maximum mass",
        "min_kg": 12000,
        "tolled_roads": "The motorways and similar roads in the RGD's annex.",
        "per_day": True, "day": "calendar",
        "rows": flat_day(int(m.group(1))),
    })


def nl_lines(path):
    t = open(path, encoding="utf-8").read()
    s = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [x.strip() for x in s.split("\n") if x.strip()]


def nl_day_table(L, start):
    """Rows of the day's table starting at index start (the "Het tarief
    voor een tijdvak van één dag" line): CO2 class, EURO class, amounts
    for at most three and at least four axles."""
    euro = {"NIET-EURO": [0], "EURO I": [1], "EURO II": [2], "EURO III": [3], "EURO IV": [4], "EURO V": [5], "EURO VI of schoner": [6]}
    amt = lambda s: int(re.fullmatch(r"€\s*(\d+)\.?", s).group(1))
    rows, k, co2 = {}, start + 1, None
    while k < len(L) and not L[k].startswith("Afdeling"):
        if L[k] == "CO" and L[k + 1] == "2":
            m = re.fullmatch(r"-emissieklasse (\d)", L[k + 2])
            if not m:
                k += 3
                continue
            co2, k = int(m.group(1)), k + 3
            if co2 > 1:
                rows[(co2, None)] = (amt(L[k]), amt(L[k + 1]))
                k += 2
            continue
        if L[k] in euro and co2 == 1:
            rows[(1, tuple(euro[L[k]]))] = (amt(L[k + 1]), amt(L[k + 2]))
            k += 3
            continue
        if (re.fullmatch(r"\d", L[k]) and not L[k - 1].endswith("CO")) or L[k] == "Terugwerkende kracht":
            break  # the next paragraph
        k += 1
    return rows


def netherlands(fetched, out):
    src_law = lambda d: {"title": f"Wet belasting zware motorrijtuigen, in force on {d} (wetten.overheid.nl)", "url": f"https://wetten.overheid.nl/jci1.3:c:BWBR0007678&g={d}&z={d}"}
    portal = {"title": "Eurovignetten portal, user description: validity from 0:00 on the first day to 24:00 on the last", "url": "https://www.eurovignettes.eu/download/Nutzerbeschreibung_20260701_EN.pdf"}
    base = {"country": "NL", "currency": "EUR", "name": "Dutch heavy vehicle tax (belasting zware motorrijtuigen, Eurovignette)",
            "vehicles": "Goods motor vehicles whose maximum mass, alone or with the trailer, is 12,000 kg or more",
            "min_kg": 12000, "tolled_roads": "Motorways (autosnelwegen).", "per_day": True, "day": "calendar"}
    old = os.path.join(fetched, "nl-bzm-2024.html")
    if os.path.exists(old) and os.path.getsize(old) > 20000:
        L = nl_lines(old)
        i = [k for k, x in enumerate(L) if x == "Artikel 10"][-1]
        j = next(k for k in range(i, i + 400) if "één dag" in L[k] or "dagtarief" in L[k].lower())
        span = " ".join(L[j:j + 6])
        m = re.search(r"€\s*(\d+)", span)
        assert m, span
        save(out, {**base, "_file": "nl-2024-01-01.json", "valid_from": "2024-01-01", "valid_to": "2025-03-24",
                   "law": f"Wet belasting zware motorrijtuigen, art. 10 (as in force on 1 January 2024, unchanged until 25 March 2025): the tax for a day is € {m.group(1)} for every vehicle. Replaced on 25 March 2025 by the amounts by CO2 class.",
                   "sources": [src_law("2024-01-01"), portal], "rows": flat_day(int(m.group(1)))})
    L = nl_lines(os.path.join(fetched, "nl-bzm-2025-03-25.html"))
    i = [k for k, x in enumerate(L) if x == "Artikel 10"][-1]
    day = [k for k in range(i, len(L)) if L[k].startswith("Het tarief voor een tijdvak van één dag")]
    assert len(day) == 2, len(day)  # the table, and its retroactive correction (Stb. 2025, 445)
    rows = nl_day_table(L, day[0])
    fix = nl_day_table(L, day[1])
    assert len(rows) == 11 and fix, (len(rows), fix)
    rows.update(fix)
    out_rows = []
    for (co2, euro), (a3, a4) in sorted(rows.items(), key=lambda x: (x[0][1] is not None, x[0])):
        sel = {"co2_class": [co2]} | ({"euro": list(euro)} if euro else {})
        out_rows.append({"component": "toll", "min_kg": 12000, "max_axles": 3, **sel, "rate": a3})
        out_rows.append({"component": "toll", "min_kg": 12000, "min_axles": 4, **sel, "rate": a4})
    save(out, {**base, "_file": "nl-2025-03-25.json", "valid_from": "2025-03-25", "valid_to": "2026-06-30",
               "law": "Wet belasting zware motorrijtuigen, art. 10 fourth paragraph, as worded by the Wet of 26 June 2024 (Stb. 2024, 240) in force 25 March 2025 (Stb. 2025, 41), and corrected with retroactive effect to that date by Stb. 2025, 445 (the Eurovignette protocol's amounts prevail): the tax for a day by CO2 emission class, EURO class (CO2 class 1) and axles (at most three, at least four, with the trailer). The law lapsed on 1 July 2026 when the vrachtwagenheffing started. Not subject to VAT.",
               "sources": [src_law("2025-03-25"), {"title": "Staatsblad 2025, 41 (entry into force 25 March 2025)", "url": "https://zoek.officielebekendmakingen.nl/stb-2025-41.pdf"}, portal],
               "rows": out_rows})


def denmark(fetched, out):
    import subprocess
    pdf = os.path.join(fetched, "dk-vejal-2020.pdf")
    txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    m = re.findall(r"5\) Dagligt uanset emissionsnorm og antallet af aksler: (\d+)", txt)
    assert len(m) == 2 and m[0] == m[1], m  # § 3, stk. 3 (to 2019) and stk. 4 (from 2020)
    assert "på under 5 pct." in txt
    save(out, {
        "_file": "dk-2020-01-01.json", "country": "DK", "currency": "DKK", "valid_from": "2020-01-01", "valid_to": "2024-12-31",
        "name": "Danish road user charge (vejbenyttelsesafgift, Eurovignette)",
        "law": f"Lov om afgift af vejbenyttelse, LBK nr. 174 af 24/02/2020, § 3, stk. 4, nr. 5: {m[1]} kroner a day for trucks registered abroad of 12 t or more, whatever their emission norm and axles; § 4 adjusts the amounts each 1 January only if the euro's value in kroner has changed by 5% or more. The period starts at the start of a day (§ 2, stk. 5). The law ended on 1 January 2025 (lov nr. 763 af 13/06/2023), replaced by the km-based vejafgift.",
        "sources": [{"title": "Lov om afgift af vejbenyttelse, LBK nr. 174 af 24/02/2020 (Retsinformation)", "url": "https://www.retsinformation.dk/eli/lta/2020/174"}],
        "vehicles": "Trucks and combinations registered abroad of 12 t or more total weight",
        "min_kg": 12000,
        "tolled_roads": "Motorways (motorvejsstrækningerne).",
        "per_day": True, "day": "calendar",
        "rows": flat_day(int(m[1])),
    })
    # 2025: the rows of 2026, checked against the 2025 report.
    cur = json.load(open(os.path.join(ROOT, "rates", "data", "dk-2026-01-01.json"), encoding="utf-8"))
    rep = open(os.path.join(fetched, "dk-trm-2025.txt"), encoding="utf-8").read()
    tables = []
    for t in ("Tabel 1", "Tabel 2", "Tabel 3"):
        seg = rep[rep.index(t):]
        vals = re.findall(r"CO2-emissionsklasse (\d)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", seg)[:5]
        tables.append({int(c): [float(x.replace(",", ".")) for x in v] for c, *v in vals})
    by = {}
    for r in cur["rows"]:
        by.setdefault((r["component"], r["co2_class"][0]), {})[r["min_kg"]] = r["rate"]
    for c in range(1, 6):
        for i, kg in enumerate((12000, 18000, 32001)):
            total = sum(by[(comp, c)][kg] for comp in ("infrastructure", "co2", "air_noise"))
            assert abs(total - tables[0][c][i]) < 1e-9, ("rate", c, kg, total, tables[0][c][i])
            assert abs(by[("env_zone_surcharge", c)][kg] - tables[1][c][i]) < 1e-9, ("zone", c, kg)
            assert abs(by[("co2", c)][kg] - tables[2][c][i]) < 1e-9, ("co2", c, kg)
    tb = {k: v for k, v in cur.items()}
    tb.update({"_file": "dk-2025-01-01.json", "valid_from": "2025-01-01", "valid_to": "2025-12-31",
               "law": "Lov om vejafgift (lov nr. 763 af 13/06/2023), § 5 stk. 1-3 as worded by lov nr. 1489 af 10/12/2024, in force 1 January 2025: the rate per km by CO2 emission class and permissible maximum mass, its split into infrastructure charge and external costs (CO2, air pollution and noise), and the surcharge in environmental zones",
               "sources": [{"title": "Lov nr. 1489 af 10/12/2024, § 1, nr. 4 (Retsinformation)", "url": "https://www.retsinformation.dk/eli/lta/2024/1489"},
                           {"title": "Transportministeriet: Afrapportering vedr. vej- og infrastrukturafgifter i Danmark, 25 March 2025 (tables 1-3)", "url": "https://www.trm.dk/media/q2wpgmh0/afrapportering-vedr-vej-og-infrastrukturafgifter-i-danmark2-a.pdf"}]})
    save(out, tb)


def main(fetched, out):
    sweden(fetched, out)
    luxembourg(fetched, out)
    netherlands(fetched, out)
    denmark(fetched, out)


if __name__ == "__main__":
    main(*sys.argv[1:])
