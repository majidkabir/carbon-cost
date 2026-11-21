"""Builds Czechia's toll tables from the annexes of the amending
regulations to nařízení vlády č. 240/2014 Sb.: 479/2020 and 299/2024 as
tabulated on epravo.cz (479/2020 from e-Sbírka when epravo.cz has no tables); 40/2024 from the Sbírka's PDF, whose annexes are
images, copied in transcribed/cz-40-2024.json (used only for the PDF with
the sha256 given there), and 299/2024 likewise (transcribed/cz-299-2024.json)
when epravo.cz's page has no tables; 327/2025 from the Sbírka's PDF text.

Usage: python3 build_cz.py fetched/ out-dir

- 479/2020 Sb. (1 January 2021 to 29 February 2024): Annex 1 (motorways)
  and 2 (class I roads), each with a table for 5:00-22:00 and one for
  22:00-5:00; by mass (over 3.5 to under 7.5 t, 7.5 to under 12 t, 12 t or
  more), EURO group (0-IV; V and EEV; VI; VI on natural gas) and axles
  (2, 3, 4, 5 or more). The table keeps the 5:00-22:00 rates; the night
  rates are about 0.5% higher. Diesel EURO VI is used for EURO VI.
- 40/2024 Sb.: from 1 March 2024 the rates by EURO group and CO2 class
  (EURO 0-IV, V/EEV, VI in CO2 class 1; CO2 classes 2-5), first for 1-24
  March (čl. I bod 12), then from 25 March 2024 (bod 13).
- 299/2024 Sb.: the same structure from 1 January 2025.
- 327/2025 Sb.: the same structure from 1 January 2026, until e-Sbírka's
  list of 240/2014's versions shows a later one (the regulation has no end).
"""
import datetime, html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

MASS = {"více než 3,5 tuny a méně než 7,5 tuny": (3501, 7499), "nejméně 7,5 tuny a méně než 12 tun": (7500, 11999), "nejméně 12 tun": (12000, 0)}
AXLES = [(2, 2), (3, 3), (4, 4), (5, 0)]
G16 = [{"euro": [0, 1, 2, 3, 4]}, {"euro": [5]}, {"euro": [6]}, None]  # the gas EURO VI column is left out
G28 = [{"co2_class": [1], "euro": [0, 1, 2, 3, 4]}, {"co2_class": [1], "euro": [5]}, {"co2_class": [1], "euro": [6]},
       {"co2_class": [2]}, {"co2_class": [3]}, {"co2_class": [4]}, {"co2_class": [5]}]


def tables(path):
    """The rate tables of an epravo page, in order: lists of (mass label,
    numbers) rows."""
    return tables_of(open(path, encoding="utf-8", errors="replace").read())


def tables_of(t):
    s = html.unescape(re.sub(r"<(td|th)[^>]*>", " | ", re.sub(r"</tr>", "\n", t)))
    s = re.sub(r"<[^>]+>", "", s).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip()]
    out, cur = [], None
    for x in lines:
        cells = [c.strip() for c in x.split("|")]
        if len(cells) > 2 and cells[1] in MASS:
            vals = [float(c.replace(",", ".")) for c in cells[2:] if c]
            if cur is None:
                cur = []
                out.append(cur)
            cur.append((cells[1], vals))
        elif cur is not None and len(cur) == 3:
            cur = None
    return out


def rows_of(table, road, groups):
    rows = []
    for label, vals in table:
        lo, hi = MASS[label]
        assert len(vals) == 4 * len(groups), (label, len(vals))
        for g, sel in enumerate(groups):
            if sel is None:
                continue
            for a, (amin, amax) in enumerate(AXLES):
                r = {"component": "toll", "road": road, "min_kg": lo}
                if hi:
                    r["max_kg"] = hi
                r["min_axles"] = amin
                if amax:
                    r["max_axles"] = amax
                rows.append(r | sel | {"rate": vals[g * 4 + a]})
    return rows


BASE = {
    "country": "CZ", "currency": "CZK", "name": "Czech electronic toll (Mýto CZ)",
    "vehicles": "Motor vehicles and combinations over 3.5 t maximum permissible mass (except buses, M2/M3, which have their own rates)",
    "min_kg": 3501, "tolled_roads": "Motorways (dálnice) and the tolled sections of class I roads (silnice I. třídy).", "motorway_share": 1,
}
SRC240 = {"title": "Nařízení vlády č. 240/2014 Sb., § 3 (rate structure)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2014/240"}


def save(out, name, tb):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, name)
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(tb["rows"]), "rows")


def main(fetched, out):
    # 479/2020: tables in order: Annex 1 day, Annex 1 night, Annex 2 day, Annex 2 night, then buses.
    # Since November 2026 epravo.cz's pages show only a regulation's start:
    # without its tables the 2021 table isn't built (the others still are).
    t = tables(os.path.join(fetched, "cz-nv-479-2020.html"))
    failed = []
    src479 = {"title": "Nařízení vlády č. 479/2020 Sb. (epravo.cz)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2020/479"}
    if len(t) < 4 or not all(len(x[0][1]) == 16 for x in t[:4]):
        # epravo.cz's page no longer shows the tables: e-Sbírka, the official Collection of Laws.
        try:
            t = annexes_479(fetched)
            src479 = {"title": "Nařízení vlády č. 479/2020 Sb. (e-Sbírka, version of 1 January 2021)", "url": ESBIRKA479}
        except (AssertionError, OSError, ValueError, KeyError) as e:
            print(f"cz-2021-01-01: 479/2020's annexes not read ({e}); not built", file=sys.stderr)
            t = None
    if t is None:
        failed.append("cz-2021-01-01")
    else:
        save(out, "cz-2021-01-01.json", {**BASE, "valid_from": "2021-01-01", "valid_to": "2024-02-29",
             "law": "Nařízení vlády č. 240/2014 Sb., § 3 and Annexes 1 (motorways) and 2 (class I roads), as worded by nařízení vlády č. 479/2020 Sb., in force 1 January 2021 to 29 February 2024: one rate per km by road category, maximum permissible mass, axles and EURO class (0-IV; V and EEV; VI). The table keeps the rates for 5:00-22:00; from 22:00 to 5:00 they are about 0.5% higher. Euro VI vehicles on natural gas or biomethane had lower rates, not in the table.",
             "sources": [src479, SRC240],
             "rows": rows_of(t[0], "motorway", G16) + rows_of(t[2], "other", G16)})
    # 40/2024: Annexes 1-2 for 1-24 March, then for 25 March on (Annexes 3-4 are buses).
    t = annexes_40(fetched)
    src = [{"title": "Nařízení vlády č. 40/2024 Sb. (epravo.cz)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2024/40"},
           {"title": "Nařízení vlády č. 40/2024 Sb., Sbírka zákonů PDF", "url": "https://epravo.cz/_dataPublic/sbirky/2024/Sb_2024_40_PZZ.pdf"}, SRC240]
    what = "one rate per km by road category, maximum permissible mass, axles, CO2 emission class and, in CO2 class 1, EURO class (0-IV; V and EEV; VI); the regulation gives no separate CO2 part"
    save(out, "cz-2024-03-01.json", {**BASE, "valid_from": "2024-03-01", "valid_to": "2024-03-24",
         "law": f"Nařízení vlády č. 240/2014 Sb., Annexes 1 and 2 as worded by čl. I bod 12 of nařízení vlády č. 40/2024 Sb., in force 1 to 24 March 2024: {what}.",
         "sources": src, "rows": rows_of(t[0], "motorway", G28) + rows_of(t[1], "other", G28)})
    save(out, "cz-2024-03-25.json", {**BASE, "valid_from": "2024-03-25", "valid_to": "2024-12-31",
         "law": f"Nařízení vlády č. 240/2014 Sb., Annexes 1 and 2 as worded by čl. I bod 13 of nařízení vlády č. 40/2024 Sb., in force 25 March to 31 December 2024: {what}.",
         "sources": src, "rows": rows_of(t[2], "motorway", G28) + rows_of(t[3], "other", G28)})
    t = [x for x in tables(os.path.join(fetched, "cz-nv-299-2024.html")) if len(x[0][1]) == 28]
    src299 = {"title": "Nařízení vlády č. 299/2024 Sb. (epravo.cz)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2024/299"}
    if len(t) != 2:
        # epravo.cz's page lost the annexes (November 2026): the Sbírka's
        # PDF, whose annexes are images, as transcribed.
        t = annexes_299(fetched)
        src299 = {"title": "Nařízení vlády č. 299/2024 Sb., Sbírka zákonů PDF", "url": "https://epravo.cz/_dataPublic/sbirky/2024/Sb_2024_299_PZZ.pdf"}
    save(out, "cz-2025-01-01.json", {**BASE, "valid_from": "2025-01-01", "valid_to": "2025-12-31",
         "law": "Nařízení vlády č. 240/2014 Sb., § 3 and Annexes 1 (motorways) and 2 (class I roads), as worded by nařízení vlády č. 299/2024 Sb., in force 1 January 2025: one rate per km by road category, maximum permissible mass, axles, CO2 emission class and, in CO2 class 1, EURO class; the regulation gives no separate CO2 part.",
         "sources": [src299, SRC240],
         "rows": rows_of(t[0], "motorway", G28) + rows_of(t[1], "other", G28)})
    t = pdf_327(fetched)
    try:
        last = until(fetched)
    except (AssertionError, OSError, ValueError, KeyError) as e:
        print(f"cz-2026-01-01: e-Sbírka's versions of 240/2014 not read ({e}); not built", file=sys.stderr)
        failed.append("cz-2026-01-01")
    else:
        tb = {"country": "CZ", "currency": "CZK", "valid_from": "2026-01-01", "name": BASE["name"],
              "law": "Nařízení vlády č. 240/2014 Sb., § 3 and Annexes 1 (motorways) and 2 (class I roads), as amended by nařízení vlády č. 327/2025 Sb., in force 1 January 2026. One rate per km by road category, maximum permissible mass, axles and EURO / CO2 emission class; the regulation gives no separate CO2 part. "
                     + (f"e-Sbírka gives this version's end as {last}." if last else "The regulation has no end date, and e-Sbírka lists no later version: the table runs until it is amended."),
              "sources": [{"title": "Nařízení vlády č. 327/2025 Sb. (2026 toll rates, Annexes 1-2)", "url": "https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2025/327"}, SRC240,
                          {"title": "e-Sbírka: nařízení vlády č. 240/2014 Sb., its versions (Historie)", "url": "https://e-sbirka.gov.cz/sb/2014/240?zalozka=historie"}],
              **{k: BASE[k] for k in ("vehicles", "min_kg", "tolled_roads", "motorway_share")},
              "rows": rows_of(t[0], "motorway", G28) + rows_of(t[1], "other", G28)}
        if last:
            tb["valid_to"] = last
        save(out, "cz-2026-01-01.json", tb)
    if failed:
        sys.exit("not built: " + ", ".join(failed))


TABLE_STARTS = ["2021-01-01", "2024-03-01", "2024-03-25", "2025-01-01", "2026-01-01"]


def until(fetched):
    """The 2026 table's last day, from e-Sbírka's list of 240/2014's
    versions (cz-esbirka-240-2014-zneni): none while the version of 1
    January 2026 (327/2025 Sb.) has no end and no later one is listed (a
    published amendment shows as a later, future version); else that day,
    with a warning."""
    z = json.load(open(os.path.join(fetched, "cz-esbirka-240-2014-zneni.html"), encoding="utf-8"))["dokumentuSbirkyZneniKeSrovnani"]
    # The tables start where e-Sbírka's versions do (from 2021), but for
    # 184/2024 Sb. (1 July 2024), which added § 6a (the EETS providers'
    # remuneration) and left the rates alone.
    starts = {v["datumUcinnostiZneniOd"] for v in z if "2021-01-01" <= (v.get("datumUcinnostiZneniOd") or "") <= "2026-01-01" and v.get("typZneni") in ("AKTUALNI", "MINULE")}
    assert starts == set(TABLE_STARTS) | {"2024-07-01"}, sorted(starts)
    assert [n["kodDokumentuSbirky"] for v in z if v.get("datumUcinnostiZneniOd") == "2024-07-01" for n in v["novely"]] == ["184/2024 Sb."]
    cur = [v for v in z if v.get("datumUcinnostiZneniOd") == "2026-01-01"]
    assert len(cur) == 1 and [n["kodDokumentuSbirky"] for n in cur[0]["novely"]] == ["327/2025 Sb."], cur
    later = sorted(v["datumUcinnostiZneniOd"] for v in z if (v.get("datumUcinnostiZneniOd") or "") > "2026-01-01")
    ends = [cur[0]["datumUcinnostiZneniDo"]] if cur[0].get("datumUcinnostiZneniDo") else []
    if later:
        ends.append((datetime.date.fromisoformat(later[0]) - datetime.timedelta(days=1)).isoformat())
    if not ends:
        return None
    print(f"::warning title=build_cz::240/2014's version of 1 January 2026 ends on {min(ends)} (e-Sbírka); read the amendment")
    return min(ends)


def flat(s):
    return re.sub(r"\s+", " ", s)


def pdf_text(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout


ESBIRKA479 = "https://e-sbirka.gov.cz/sb/2020/479/2021-01-01"


def annexes_479(fetched):
    """479/2020's Annexes 1 and 2 from e-Sbírka, the official Collection of
    Laws: its fragments API gives the regulation's text, the annexes' tables
    as HTML. Each annex has a table for 5:00-22:00 and one for 22:00-5:00,
    three rows of 16 rates each; in order, as epravo.cz's tables: Annex 1
    day, Annex 1 night, Annex 2 day, Annex 2 night."""
    d = json.load(open(os.path.join(fetched, "cz-esbirka-479-2020-0.html"), encoding="utf-8"))
    assert d.get("pocetStranek") == 1, f"e-Sbírka lists {d.get('pocetStranek')} pages"
    frags = d["seznam"]
    text = flat(" ".join(re.sub(r"<[^>]+>", " ", html.unescape(f.get("xhtml") or "")) for f in frags))
    assert "NAŘÍZENÍ VLÁDY ze dne 16. listopadu 2020" in text and "nabývá účinnosti dnem 1. ledna 2021" in text, "not 479/2020"
    annex, by = None, {1: "", 2: ""}
    for f in frags:
        m = re.search(r"Příloha č\. (\d+) k nařízení vlády č\. 240/2014", f.get("xhtml") or "")
        if f["kodTypuFragmentu"] == "Hlavicka_priloha" and m:
            annex = int(m.group(1))
        elif f["kodTypuFragmentu"] == "Tabulka" and annex in by:
            by[annex] += f["xhtml"] + "\n"
    out = []
    for n in (1, 2):
        t = tables_of(by[n])
        assert [(len(x), len(x[0][1])) for x in t] == [(3, 16), (3, 16)], (n, [(len(x), len(x[0][1])) for x in t])
        out += t
    return out


def annexes_40(fetched):
    """40/2024's Annexes 1 and 2 under čl. I body 12 and 13, as transcribed
    from its PDF's images, for the PDF fetched."""
    tr = json.load(open(os.path.join(HERE, "transcribed", "cz-40-2024.json"), encoding="utf-8"))
    files = {f["url"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    f = files.get(tr["source"]["url"])
    if f is None or f["sha256"] != tr["source"]["sha256"]:
        sys.exit("cz-40-2024: the fetched PDF isn't the one transcribed")
    text = flat(pdf_text(os.path.join(fetched, f["file"])))
    for want in ("12. Přílohy č. 1 až 4 včetně nadpisů znějí:", "13. Přílohy č. 1 až 4 včetně nadpisů znějí:",
                 "Toto nařízení nabývá účinnosti dnem 1. března 2024, s výjimkou ustanovení čl. I bodu 13, které nabývá účinnosti dnem 25. března 2024."):
        assert want in text, want
    out = []
    for bod in (12, 13):
        for annex, road in ((1, "motorway"), (2, "other")):
            g = next(x for x in tr["tables"] if (x["bod"], x["annex"], x["road"]) == (bod, annex, road))
            assert list(g["rows"]) == list(MASS), list(g["rows"])
            out.append([(m, [float(v.replace(",", ".")) for v in g["rows"][m].split()]) for m in MASS])
    return out


def annexes_299(fetched):
    """299/2024's Annexes 1 and 2, as transcribed from its PDF's images, for
    the PDF fetched."""
    tr = json.load(open(os.path.join(HERE, "transcribed", "cz-299-2024.json"), encoding="utf-8"))
    files = {f["url"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    f = files.get(tr["source"]["url"])
    if f is None or f["sha256"] != tr["source"]["sha256"]:
        sys.exit("cz-299-2024: the fetched PDF isn't the one transcribed")
    text = flat(pdf_text(os.path.join(fetched, f["file"])))
    for want in ("Přílohy č. 1 a 2 k nařízení vlády č. 240/2014 Sb.", "včetně nadpisů znějí:", "Toto nařízení nabývá účinnosti dnem 1. ledna 2025."):
        assert want in text, want
    out = []
    for annex, road in ((1, "motorway"), (2, "other")):
        g = next(x for x in tr["tables"] if (x["annex"], x["road"]) == (annex, road))
        assert list(g["rows"]) == list(MASS), list(g["rows"])
        out.append([(m, [float(v.replace(",", ".")) for v in g["rows"][m].split()]) for m in MASS])
    return out


def pdf_327(fetched):
    """327/2025's Annexes 1 and 2 (čl. I body 1 and 2) from the Sbírka PDF's
    text: three rows of 28 rates each; the consolidated text of 240/2014
    printed with it gives the same rates."""
    text = pdf_text(os.path.join(fetched, "cz-nv-327-2025-pdf.pdf"))
    assert "Toto nařízení nabývá účinnosti dnem 1. ledna 2026." in flat(text)

    def rates(part):
        rows = [[float(x.replace(",", ".")) for x in re.findall(r"\b\d,\d{4}\b", ln)] for ln in part.splitlines()]
        rows = [r for r in rows if r]
        assert all(len(r) == 28 for r in rows) and len(rows) == 3, [len(r) for r in rows]
        return list(zip(MASS, rows))

    a1, a2, a4 = (text.index(x) for x in ("1. Příloha č. 1 zní:", "2. Příloha č. 2 zní:", "3. Příloha č. 4 zní:"))
    amended = [rates(text[a1:a2]), rates(text[a2:a4])]
    full = text.index("Úplné znění aktu č. 240/2014 Sb.")
    c1 = text.index("Příloha č. 1", text.index("§7", full))
    c2, c3 = text.index("Příloha č. 2", c1), text.index("Příloha č. 3", c1)
    assert [rates(text[c1:c2]), rates(text[c2:c3])] == amended, "the consolidated text's Annexes 1-2 differ"
    return amended


if __name__ == "__main__":
    main(*sys.argv[1:])
