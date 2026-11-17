"""Builds the Swiss (and Liechtenstein) LSVA tables for 2024 from the
Federal Council's media release attachment on the 2025 tariff change,
which gives the tariffs per fee category until 31 December 2024 and from
1 January 2025, and the categories: EURO 0 to V in category 1 (the most
expensive), EURO VI in category 3.

Usage: python3 build_ch.py fetched/ out-dir

The fee is per km and tonne of the vehicle's maximum permissible mass
(at most 40 t: SVAV Art. 6 para. 3 in 2024), on all roads. Electric
trucks were exempt (SVAG Art. 4 para. 3, SVAV Art. 3 para. 1 let. e).
Liechtenstein charges the same under the customs treaty.
"""
import json, os, re, subprocess, sys


def main(fetched, out):
    t = re.sub(r"\s+", " ", open(os.path.join(fetched, "ch-lsva-2025-media.txt"), encoding="utf-8").read())
    m = {int(c): float(old.replace(",", ".")) for c, old, new in re.findall(r"\b([123]) (\d,\d\d) Rp\. (\d,\d\d) Rp\.", t)}
    assert set(m) == {1, 2, 3}, m
    assert "Euro 0 bis V sind in der teuersten Abgabekategorie 1" in t and "EURO VI in der billigsten Abgabekategorie 3" in t
    rows = [{"component": "distance_fee", "euro": [6], "rate": round(m[3] / 100, 6)}, {"component": "distance_fee", "rate": round(m[1] / 100, 6)}]
    src = {"title": "Federal Council media release attachment (BAV): LSVA tariffs until 31.12.2024 and from 1.1.2025", "url": "https://www.newsd.admin.ch/newsd/message/attachments/84723.pdf"}
    common = {"currency": "CHF", "valid_from": "2024-01-01", "valid_to": "2024-12-31",
              "vehicles": "Motor vehicles and trailers over 3.5 t total weight used for goods transport, Swiss or foreign",
              "min_kg": 3501, "tolled_roads": "All public roads: the fee is per km driven anywhere in Switzerland and Liechtenstein.",
              "per_tonne_km": True, "max_chargeable_kg": 40000,
              "exemptions": [{"co2_class": [5], "until": "2024-12-31", "note": "Motor vehicles with electric drive are exempt."}],
              "rows": rows}
    law = f"{m[1]:.2f} / {m[2]:.2f} / {m[3]:.2f} Rappen per tonne-km for fee categories 1 / 2 / 3 until 31 December 2024; EURO 0-V in category 1, EURO VI in category 3; chargeable weight at most 40 t."
    os.makedirs(out, exist_ok=True)
    for cc, name, lawname, extra in (
        ("CH", "Swiss performance-related heavy vehicle fee (LSVA / RPLP)", "Schwerverkehrsabgabeverordnung (SVAV, SR 641.811) of 6 March 2000, Art. 14 and Annex 1 as in force in 2024: ", []),
        ("LI", "Liechtenstein performance-related heavy vehicle fee (LSVA, as in Switzerland)", "Liechtenstein's Schwerverkehrsabgabeverordnung (LGBl. 2000 Nr. 275) as in force in 2024, applying the Swiss tariff under the customs treaty: ", []),
    ):
        tb = {"country": cc, **common, "name": name, "law": lawname + law, "sources": [src] + extra}
        path = os.path.join(out, f"{cc.lower()}-2024-01-01.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(rows), "rows")

    current(fetched, out)


def art_rates(text):
    """Rappen per tonne-km for fee categories 1-3 from the tariff article."""
    m = {int(c): float(r.replace(",", ".")) for r, c in re.findall(r"(\d,\d\d) Rappen für die Abgabekategorie ([123])", text)}
    if set(m) != {1, 2, 3}:
        sys.exit(f"tariff: {m}")
    return m


def pdf_text(path):
    txt = path[:-4] + ".txt"
    if not os.path.exists(txt):
        subprocess.run(["pdftotext", "-layout", path, txt], check=True)
    return re.sub(r"\s+", " ", open(txt, encoding="utf-8").read())


EXEMPT_UNTIL = "2030-12-31"  # the revised Heavy Vehicle Fee Act adopted on 2 October 2026 keeps electric trucks exempt until the end of 2030


def current(fetched, out):
    """From 1 January 2025: the Swiss SVAV of 27 March 2024 (Art. 8) and
    Liechtenstein's of 3 December 2024 (LGBl. 2024 Nr. 452, Art. 7)."""
    common = {"vehicles": "Motor vehicles and trailers over 3.5 t total weight used for goods transport, Swiss or foreign",
              "min_kg": 3501, "tolled_roads": "All public roads: the fee is per km driven anywhere in Switzerland and Liechtenstein.",
              "per_tonne_km": True, "max_chargeable_kg": 40000}
    for cc, sid, checks, name, law, sources, note in (
        ("CH", "ch-svav-2025", ["vom 27. März 2024", "Fassung gemäss Ziff. I der V vom 20. Sept. 2024, in Kraft seit 1. Jan. 2025",
                                "Das massgebende Gewicht beträgt in jedem Fall höchstens 40 t.", "Motorfahrzeuge mit elektrischem Antrieb",
                                "1.3 Abgabekategorie 3 – EURO VI / EURO 6 oder später"],
         "Swiss performance-related heavy vehicle fee (LSVA / RPLP)",
         "Schwerverkehrsabgabeverordnung (SVAV, SR 641.811) of 27 March 2024, Art. 8 para. 1 as amended 20 September 2024 (AS 2024 522), in force 1 January 2025: {r} Rappen per tonne-km for fee categories 1 / 2 / 3; Annex 1: EURO VI in category 3, EURO 0-V in category 1; Art. 6 para. 3: chargeable weight at most 40 t.",
         [{"title": "SVAV (SR 641.811), consolidated text as of 1 October 2025, Art. 8 tariff and Annex 1 fee categories", "url": "https://www.fedlex.admin.ch/eli/cc/2024/150/de"},
          {"title": "BAZG: LSVA general information and tariffs", "url": "https://www.bazg.admin.ch/bazg/en/home/informationen-firmen/verkehrsabgaben-und-strassenverkehrsrecht/schwerverkehrsabgaben-lsva-und-psva/lsva_allgemeines_tarife.html"}],
         "Motor vehicles with electric drive are exempt (SVAV Art. 2 para. 1 let. k); the revised Heavy Vehicle Fee Act adopted on 2 October 2026 keeps them exempt until the end of 2030."),
        ("LI", "li-svav-2024-452", ["Schwerverkehrsabgabe (Schwerverkehrsabgabeverordnung, SVAV), LGBl.", "3) Das massgebende Gewicht beträgt in jedem Fall höchstens 40 t.",
                                    "1.3 Abgabekategorie 3 - EURO VI / EURO 6 oder später"],
         "Liechtenstein performance-related heavy vehicle fee (LSVA, as in Switzerland)",
         "Schwerverkehrsabgabeverordnung (SVAV) of 3 December 2024, LGBl. 2024 Nr. 452, Art. 7 para. 1: {r} Rappen per tonne-km for fee categories 1 / 2 / 3; Annex: EURO VI in category 3; Art. 5 para. 3: chargeable weight at most 40 t.",
         [{"title": "Liechtenstein SVAV, LGBl. 2024 Nr. 452, consolidated version of 1 October 2025", "url": "https://www.gesetze.li/konso/pdf/2024452000"}],
         "Motor vehicles with electric drive are exempt, as in Switzerland (SVAG Art. 5 para. 1 let. i)."),
    ):
        t = pdf_text(os.path.join(fetched, sid + ".pdf"))
        for c in checks:
            if c not in t:
                sys.exit(f"{sid}: no {c!r}")
        m = art_rates(t)
        tb = {"country": cc, "currency": "CHF", "valid_from": "2025-01-01", "valid_to": EXEMPT_UNTIL, "name": name,
              "law": law.format(r=" / ".join(f"{m[c]:.2f}" for c in (1, 2, 3))), "sources": sources, **common,
              "exemptions": [{"co2_class": [5], "until": EXEMPT_UNTIL, "note": note}],
              "rows": [{"component": "distance_fee", "euro": [6], "rate": round(m[3] / 100, 6)}, {"component": "distance_fee", "rate": round(m[1] / 100, 6)}]}
        path = os.path.join(out, f"{cc.lower()}-2025-01-01.json")
        json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, tb["rows"])


if __name__ == "__main__":
    main(*sys.argv[1:])
