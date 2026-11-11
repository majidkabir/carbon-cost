"""Builds Austria's historical toll tables from the Mauttarifverordnung
of each year (BGBl. II), as pdftotext gives it.

Usage: python3 build_at.py fetched/ out-dir

Each Mauttarifverordnung sets, in cents or euros without VAT:
§ 2 the infrastructure tariff per km by tariff group (E: CO2 class 5;
A: the others) and category (2, 3, 4+ axles); § 3 a 25% surcharge on the
A 12 Kufstein - Innsbruck/Amras; § 4 the fixed infrastructure tariffs of
the special toll sections a) to q); § 5 their night (22:00-05:00) tariffs
for 4+ axles on the A 13; § 8 the air pollution and noise tariff by EURO
group (E zero-emission, A EURO VI, B V/EEV, C IV, D 0-III); § 9 b) the
CO2 tariff by CO2 class (for vehicles other than buses).

The sections' ends and the A 12 stretch are those of
rates/data/at-2026-01-01.json (OpenStreetMap junctions); the script
checks that each year names the same sections.
"""
import copy, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
YEARS = [  # (file, valid_from, valid_to, title, BGBl, RIS URL)
    ("at-mtv-2023", "2024-01-01", "2024-12-31", "Mauttarifverordnung 2023", "BGBl. II Nr. 331/2023", "https://ris.bka.gv.at/Dokumente/BgblAuth/BGBLA_2023_II_331/BGBLA_2023_II_331.html"),
    ("at-mtv-2024", "2025-01-01", "2025-12-31", "Mauttarifverordnung 2024", "BGBl. II Nr. 410/2024", "https://ris.bka.gv.at/Dokumente/BgblAuth/BGBLA_2024_II_410/BGBLA_2024_II_410.pdf"),
]
AXLES = [{"min_axles": 2, "max_axles": 2}, {"min_axles": 3, "max_axles": 3}, {"min_axles": 4}]


def nums(line):
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+,\d+", line)]


def build(txt, tmpl, frm, to, title, bgbl, url):
    par = lambda n: txt.index(f"§ {n}.")
    tb = copy.deepcopy(tmpl)
    rows = []
    # § 2 infrastructure, cents.
    seg = txt[par(2):par(3)]
    infra = {g: nums(re.search(rf"^\s*{g}\s+([\d,\s]+)$", seg, re.M).group(1)) for g in "EA"}
    for g, cls in (("E", [5]), ("A", [1, 2, 3, 4])):
        for a, v in zip(AXLES, infra[g]):
            rows.append({"component": "infrastructure", "min_kg": 3501, **a, "rate": round(v / 100, 6), "co2_class": cls})
    # § 8 air pollution and noise, cents.
    seg = txt[par(8):par(9)]
    euro = {"E": None, "A": [6], "B": [5], "C": [4], "D": [0, 1, 2, 3]}
    for g, e in euro.items():
        vals = nums(re.search(rf"^\s*{g}\s+([\d,\s]+)$", seg, re.M).group(1))
        for a, v in zip(AXLES, vals):
            sel = {"co2_class": [5]} if e is None else {"co2_class": [1, 2, 3, 4], "euro": e}
            rows.append({"component": "air_noise", "min_kg": 3501, **a, "rate": round(v / 100, 6)} | sel)
    # § 9 b) CO2, cents, other vehicles than buses.
    # MTV 2024 on: b) for vehicles other than buses; MTV 2023: one table.
    seg = txt[txt.index("b) andere Kraftfahrzeuge", par(9)):] if "b) andere Kraftfahrzeuge" in txt else txt[par(9):par(10)]
    for c in (5, 4, 3, 2, 1):
        vals = nums(re.search(rf"^\s*{c}\s+([\d,\s]+)$", seg, re.M).group(1))
        for a, v in zip(AXLES, vals):
            rows.append({"component": "co2", "min_kg": 3501, **a, "rate": round(v / 100, 6), "co2_class": [c]})
    tb["rows"] = rows
    # § 4 sections, euros.
    seg = txt[par(4):par(5)]
    blocks = re.split(r"\n\s*([a-q])\) ", seg)[1:]
    secs = {blocks[i]: blocks[i + 1] for i in range(0, len(blocks), 2)}
    for s in tb["sections"]["list"]:
        b = secs[s["id"]]
        head = re.sub(r"\s+", " ", b.split("\n")[0]).replace(" bis ", " – ")
        assert head.split(",")[0] == s["name"].split(",")[0], (head, s["name"])
        s["tariff"] = {g: nums(re.search(rf"^\s*{g}\s+([\d,\s]+)$", b, re.M).group(1)) for g in "EA"}
        assert all(len(v) == 3 for v in s["tariff"].values()), s["tariff"]
    # § 5 night tariffs, A 13 sections h) to p), in order.
    seg = txt[par(5):par(6)]
    night = [nums(l) for l in seg.splitlines() if re.match(r"\s*A 13\b", l) and len(nums(l)) == 2]
    a13 = [s for s in tb["sections"]["list"] if s.get("night_kat4")]
    assert len(night) == len(a13), (len(night), len(a13))
    for s, (e, a) in zip(a13, night):
        s["night_kat4"] = {"E": e, "A": a}
    assert "um einen Aufschlag in der Höhe von 25 %" in re.sub(r"\s+", " ", txt[par(3):par(4)])
    tb.update({"valid_from": frm, "valid_to": to,
               "law": f"{title}, {bgbl}, §§ 1-2, 7-9 (in force {frm})",
               "sources": [{"title": f"{title}, {bgbl} (RIS)", "url": url}]})
    tb["sections"]["law"] = re.sub(r"Mauttarifverordnung \d{4}, BGBl\. II Nr\. \d+/\d{4}", f"{title}, {bgbl}", tb["sections"]["law"])
    for sc in tb.get("surcharges", []):
        sc["law"] = re.sub(r"Mauttarifverordnung \d{4}", title, sc["law"])
    return tb


def check_asfinag(fetched, frm, tb):
    """ASFINAG's rate sheet for the year (at-asfinag-<year>.txt), if fetched,
    gives the total per km by CO2 and EURO class: it must be the sum of the
    table's parts."""
    p = os.path.join(fetched, f"at-asfinag-{frm[:4]}.txt")
    if not os.path.exists(p):
        return
    txt = open(p, encoding="utf-8").read()
    m = re.search(r"CO2 emission class 1\s+EURO VI\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", txt)
    want = [float(x.replace(",", ".")) for x in m.groups()]
    for i, a in enumerate(AXLES):
        got = sum(r["rate"] for r in tb["rows"] if r["min_axles"] == a["min_axles"] and 1 in r["co2_class"] and r.get("euro", [6]) == [6])
        assert abs(got - want[i]) < 1e-6, (frm, a, got, want[i])
    print("ASFINAG totals agree:", want)


def main(fetched, out):
    tmpl = json.load(open(os.path.join(ROOT, "rates", "data", "at-2026-01-01.json"), encoding="utf-8"))
    for f, frm, to, title, bgbl, url in YEARS:
        # The fetched text, else one read in a browser (tools/history/browser/,
        # for RIS, which refuses scripted requests).
        p = next((x for x in (os.path.join(fetched, f + ".txt"), os.path.join(HERE, "browser", f + ".txt")) if os.path.exists(x)), "")
        if not p:
            print("missing", f)
            continue
        tb = build(open(p, encoding="utf-8").read(), tmpl, frm, to, title, bgbl, url)
        if os.path.dirname(p) != fetched:
            tb["law"] += f"; the text read in a browser into tools/history/browser/{f}.txt"
        check_asfinag(fetched, frm, tb)
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"at-{frm}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(tb["rows"]), "rows,", len(tb["sections"]["list"]), "sections")


if __name__ == "__main__":
    main(*sys.argv[1:])
