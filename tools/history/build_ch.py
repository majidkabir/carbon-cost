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
import json, os, re, sys


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


if __name__ == "__main__":
    main(*sys.argv[1:])
