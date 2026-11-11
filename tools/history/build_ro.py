"""Builds Romania's tables before 8 October 2026 from the texts the
history workflow fetched (tools/history/sources.json, ro-*):

- the rovinieta (tarif de utilizare) of Ordonanța Guvernului nr. 15/2002
  until 30 September 2026: a time-based charge in euro, the 1-day tariff
  of Anexa nr. 1 for goods vehicles over 3.5 t (categories C to F), read
  from each consolidation of the ordinance on the Portal Legislativ
  (Internet Archive copies) and checked against CNAIR's table of
  8 September 2025;
- TollRo from 1 to 7 October 2026 under Ordinul MTI nr. 1.925/2025: the
  current table's rates for combustion trucks (Ordinul MTI nr. 959/2026
  of 8 October 2026 replaced the annex, keeping those rates and adding
  a rate for electric trucks; the 1.925/2025 annex had none, so they are
  priced at the EURO VI rate here).

The end of the rovinieta and the start of TollRo are Legea nr. 226/2023
art. 24 and 29 as consolidated on 30 September 2026 (Legea nr. 103/2026),
read from the copy CNAIR publishes on eToll.

Usage: python3 build_ro.py fetched/ out-dir"""
import html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

CATS = {  # OG 15/2002 Anexa nr. 1 categories: the vehicle or combination's MTMA and axles (art. 1 alin. (1) lit. a))
    "C": {"min_kg": 3501, "max_kg": 7500},
    "D": {"min_kg": 7501, "max_kg": 11999},
    "E": {"min_kg": 12000, "max_axles": 3},
    "F": {"min_kg": 12000, "min_axles": 4},
}

# Each consolidation in force on a day of the period, the 1-day tariffs
# it must show, and the VAT rate included in them (19%, 21% from 1 August
# 2025 under Legea nr. 141/2025 art. II and VII).
PERIODS = [
    {"valid_from": "2024-01-01", "valid_to": "2025-07-31", "vat": 1.19,
     "forms": [("ro-og15-20231216", "16.12.2023"), ("ro-og15-20240129", "29.01.2024"), ("ro-og15-20240311", "11.03.2024")],
     "law": "Ordonanța Guvernului nr. 15/2002, art. 1 and Anexa nr. 1 (as last replaced by OUG nr. 44/2017, and by OG nr. 14/2024 from 11 March 2024 with the same tariffs for these categories)"},
    {"valid_from": "2025-08-01", "valid_to": "2025-09-07", "vat": 1.21,
     "forms": [("ro-og15-20250728", "28.07.2025")],
     "law": "Ordonanța Guvernului nr. 15/2002, art. 1 and Anexa nr. 1 (Legea nr. 141/2025 replaced the annex from 1 September 2025 with the same tariffs for these categories)"},
    {"valid_from": "2025-09-08", "valid_to": "2026-09-30", "vat": 1.21,
     "forms": [("ro-og15-20250908", "08.09.2025")], "cnair": True,
     "law": "Ordonanța Guvernului nr. 15/2002, art. 1 and Anexa nr. 1 as replaced by OG nr. 23/2025 (Monitorul Oficial nr. 808 of 29 August 2025) from 8 September 2025"},
]


def text(path):
    h = open(path, encoding="utf-8", errors="replace").read()
    sel = re.search(r"id='fa_selectata'[^>]*>([0-9.]+)", h)
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    return (sel.group(1) if sel else None), t


def tariffs(t):
    """Each Anexa nr. 1 table in the text: {category: 1-day euro}."""
    out = []
    for m in re.finditer(r"NIVELUL tarifului de utilizare a drumurilor na[țţ]ionale", t):
        seg = t[m.start():m.start() + 4000]
        if "TVA inclus" not in seg[:300]:
            sys.exit("annex heading without 'TVA inclus'")
        seg = seg.split("Anexa nr. 2")[0]
        r = {}
        for c in CATS:
            mm = re.search(r"\b" + c + r" Vehicul.{0,200}? 1 zi ([0-9]+(?:,[0-9]+)?)", seg)
            if not mm:
                sys.exit(f"no 1-day tariff for {c}")
            r[c] = float(mm.group(1).replace(",", "."))
        out.append(r)
    return out


def check_rules(t):
    for want in ("Perioada de valabilitate a rovinietei începe de la ora 0,00 a zilei solicitate de utilizator și expiră la ora 24,00",
                 "cu excepția sectoarelor de drum național aflate în intravilanul municipiilor",
                 "un ansamblu format dintr-un autovehicul și semiremorca ori remorcile tractate de acesta"):
        if want not in t:
            sys.exit(f"OG 15/2002 no longer says {want!r}")


def pdftext(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    srcs = {s["id"]: s for s in json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))["sources"]}
    l226 = re.sub(r"\s+", " ", pdftext(os.path.join(fetched, "ro-etoll-l226.pdf")))
    for want in ("Consolidarea din data de 30 septembrie 2026", "L 103/2026",
                 "Ordonanţa Guvernului nr. 15/2002 privind aplicarea tarifului de utilizare şi a tarifului de trecere pe reţeaua de drumuri naţionale din România, publicată în Monitorul Oficial al României, Partea I, nr. 82 din 1 februarie 2002, aprobată cu modificări şi completări prin Legea nr. 424/2002, cu modificările şi completările ulterioare, se abrogă de la data de 1 octombrie 2026",
                 "Aplicarea rovinietei şi TollRo de către CNAIR, conform dispoziţiilor prezentei legi, se realizează începând cu data de 1 octombrie 2026"):
        if want not in l226:
            sys.exit(f"Legea 226/2023 copy: no {want!r}")
    cnair = re.sub(r"\s+", " ", pdftext(os.path.join(fetched, "ro-cnadnr-tabele.pdf")))
    l141 = pdftext(os.path.join(fetched, "ro-l141-2025.pdf"))
    if "nivelul acesteia este 21%" not in l141 or "intră în vigoare la data de 1 august 2025" not in re.sub(r"\s+", " ", l141):
        sys.exit("Legea 141/2025: no 21% VAT from 1 August 2025")
    for p in PERIODS:
        seen = None
        for sid, form in p["forms"]:
            sel, t = text(os.path.join(fetched, sid + ".html"))
            if sel != form:
                sys.exit(f"{sid}: consolidation {sel}, not {form}")
            check_rules(t)
            for r in tariffs(t):
                if seen is not None and r != seen:
                    sys.exit(f"{sid}: tariffs {r} differ from {seen}")
                seen = r
        if p.get("cnair"):
            for c, v in seen.items():
                if not re.search(r"\b" + c + r" Vehicul de transport marfă cu MTMA .{0,60}? 1 zi " + f"{v:.1f}".replace(".", ","), cnair):
                    sys.exit(f"CNAIR table: {c} isn't {v}")
        rows = [{"component": "toll", **CATS[c], "rate": round(v / p["vat"], 4)} for c, v in seen.items()]
        sources = [{"title": srcs[sid]["what"], "url": srcs[sid]["url"]} for sid, _ in p["forms"]]
        for sid in (["ro-l141-2025"] if p["valid_from"] >= "2025-08-01" else []) + (["ro-cnadnr-tabele"] if p.get("cnair") else []):
            sources.append({"title": srcs[sid]["what"], "url": srcs[sid]["url"]})
        if p["valid_to"] == "2026-09-30":
            sources.append({"title": srcs["ro-etoll-l226"]["what"] + ", consolidated on 30 September 2026", "url": srcs["ro-etoll-l226"]["url"]})
        tb = {"country": "RO", "currency": "EUR", "valid_from": p["valid_from"], "valid_to": p["valid_to"],
              "name": "Romanian road user charge (rovinieta)",
              "law": p["law"] + ": the rovinieta is a time-based charge in euro, including VAT, for periods from 1 day to 12 months, by the maximum authorised mass of the vehicle or combination and its axles: "
                     + ", ".join(f"{c} {v:g} euro a day" for c, v in seen.items())
                     + " (C over 3.5 to 7.5 t, D over 7.5 to under 12 t, E 12 t and over with up to 3 axles, F 12 t and over with 4 or more). A day runs from 00:00 to 24:00 (art. 1 alin. (8)). Paid in lei at the BNR rate of the month before (art. 6). "
                     + f"Rates here exclude {round((p['vat'] - 1) * 100)}% VAT. Bridge tolls (tarif de trecere: Fetești–Cernavodă, Giurgeni–Vadu Oii, Giurgiu–Ruse) aren't included."
                     + (" Legea nr. 226/2023 (art. 24, art. 29, as prorogued by Legea nr. 103/2026) repealed the ordinance and started TollRo on 1 October 2026." if p["valid_to"] == "2026-09-30" else ""),
              "sources": sources,
              "vehicles": "Goods vehicles over 3.5 t maximum authorised mass (the vehicle or combination)",
              "min_kg": 3501,
              "tolled_roads": "National roads, expressways and motorways, except national roads inside municipalities (between the town entry and exit signs).",
              "per_day": True, "day": "calendar", "rows": rows}
        path = os.path.join(out, f"ro-{p['valid_from']}.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, {r["rate"] for r in rows}, seen)
    tollro(out)


def tollro(out):
    """TollRo 1-7 October 2026: the 8 October table's combustion rates."""
    cur = json.load(open(os.path.join(HERE, "..", "..", "rates", "data", "ro-2026-10-08.json"), encoding="utf-8"))
    if "959/2026 of 8 October 2026" not in cur["law"]:
        sys.exit("ro-2026-10-08 isn't the OMTI 959/2026 table")
    rows = []
    for r in cur["rows"]:
        if "co2_class" in r:
            continue
        rows.append(r)
        if 6 in r.get("euro", []):
            rows.append({k: v for k, v in r.items() if k != "euro"} | {"co2_class": [5]})
    tb = dict(cur)
    tb.update({
        "valid_from": "2026-10-01", "valid_to": "2026-10-07",
        "law": "Legea nr. 226/2023 (TollRo from 1 October 2026, art. 29 as prorogued by Legea nr. 103/2026): TollRo is the unit rate times the km driven on the SETRE România network. Unit rates in lei/km including 21% VAT from Ordinul MTI nr. 1.925/2025 (Monitorul Oficial nr. 940/2025), by maximum authorised mass (I over 3.5 to 7.5 t, II over 7.5 to under 12 t, III 12 t and over), road category (motorways and expressways, or national roads) and EURO class. Ordinul MTI nr. 959/2026 replaced the annex from 8 October 2026 keeping these rates and adding a rate for electric trucks; the 1.925/2025 annex had none, so electric trucks are priced at the EURO VI rate here. Rates here exclude VAT (divided by 1.21).",
        "sources": [{"title": "Ordinul MTI nr. 1.925/2025 (Portal Legislativ)", "url": "https://legislatie.just.ro/Public/DetaliiDocument/302972"},
                    {"title": "CNAIR eToll: TollRo rates in force (OMTI 959/2026), the rates here", "url": "https://portal.etoll.ro/web/guest/tollro"},
                    {"title": "CNAIR eToll: Legea nr. 226/2023, consolidated on 30 September 2026", "url": "https://portal.etoll.ro/documents/d/guest/legea-nr-226-2023-privind-aplicarea-unor-tarife-rutiere-pe-reteaua-de-drumuri-nationale-din-romania"}],
        "rows": rows,
    })
    path = os.path.join(out, "ro-2026-10-01.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
