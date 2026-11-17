"""Builds Iceland's kílómetragjald tables for 2024 and 2025, before Lög nr.
100/2025: the km fee of Lög um olíugjald og kílómetragjald nr. 87/2004 on
trucks (not buses) and trailers of 10,000 kg or more, each by its own
gjaldþyngd (its permissible total weight), with no maximum by axles. The
amounts per year come from Skatturinn's page on the fee (fetched as
is-skatturinn-km.html: "Almennt kílómetragjald <year>" tables).

Usage: python3 build_is.py fetched/ out-dir"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import is_km  # noqa: E402

URL = "https://www.skatturinn.is/atvinnurekstur/skattar-og-gjold/kilometragjald-a-vorubifreidar/"
YEARS = ("2024", "2025")


def read(t, year):
    """The year's bands (lower kg, upper kg or None, ISK per km)."""
    m = re.search(rf"Almennt kílómetragjald {year} Leyfð heildarþyngd ökutækis, kg Kílómetragjald, kr\. .{{0,80}}?(10\.000–11\.000 .{{0,900}}?) og yfir (\d+,\d\d)", t)
    if not m:
        return None
    pairs = re.findall(r"(\d{1,2}\.\d{3})–(\d{1,2}\.\d{3}) (\d+,\d\d)", m.group(1))
    top = re.search(r"(\d{1,2}\.\d{3})$", m.group(1).strip())
    bands = sorted((is_km.kg(a), is_km.kg(b), is_km.kr(r)) for a, b, r in pairs)
    for (lo, hi, _), (lo2, _, _) in zip(bands, bands[1:]):
        if lo2 != hi + 1:
            sys.exit(f"build_is: {year}: bands not contiguous at {hi}")
    if not top or len(bands) != 21 or bands[0][0] != 10000:
        sys.exit(f"build_is: {year}: {len(bands)} bands read, not 21 from 10,000 kg")
    # Skatturinn writes the top band "31.000 og yfir": above the band that ends at 31,000.
    return bands + [(bands[-1][1] + 1, None, is_km.kr(m.group(2)))]


def main(fetched, out):
    p = os.path.join(fetched, "is-skatturinn-km.html")
    if not os.path.exists(p):
        print("::warning title=build_is::is-skatturinn-km not fetched")
        return
    t = is_km.text(p)
    for year in YEARS:
        bands = read(t, year)
        if not bands:
            sys.exit(f"build_is: Almennt kílómetragjald {year} not found")
        rows = []
        for unit in ("motor", "trailer"):
            if unit == "motor":
                # Trucks under 10,000 kg pay none of it.
                rows.append({"component": "toll", "vehicle_unit": "motor", "max_kg": 9999, "rate": 0})
            for lo, hi, r in bands:
                row = {"component": "toll", "vehicle_unit": unit, "min_kg": lo, "rate": r}
                if hi is not None:
                    row["max_kg"] = hi
                rows.append(row)
        tb = {"country": "IS", "currency": "ISK", "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
              "name": "Kílómetragjald (km fee on trucks and trailers of 10 t or more)",
              "law": (f"Lög um olíugjald og kílómetragjald nr. 87/2004: the km fee on trucks (not buses) and trailers of 10,000 kg or more, "
                      "registered in Iceland or abroad, each by its own gjaldþyngd (its permissible total weight; no maximum by axles), "
                      f"ISK {bands[0][2]:.2f} per km at 10,000-11,000 kg to {bands[-1][2]:.2f} above {bands[-2][1]:,} kg in {year}, "
                      "as Skatturinn (Iceland Revenue and Customs) gives the year's amounts. The motor vehicle and the trailer each pay on their own "
                      "(give motor_mass_kg, trailer_mass_kg and motor_axles). The special km fee on vehicles for special use is left out. "
                      "Diesel paid olíugjald, a fuel excise, besides: not a road charge here."),
              "sources": [{"title": f"Skatturinn: Kílómetragjald á vörubifreiðar og eftirvagna (Almennt kílómetragjald {year})", "url": URL}],
              "vehicles": "Trucks and trailers of 10,000 kg or more", "min_kg": 0,
              "tolled_roads": "All roads (by odometer).", "rows": rows}
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"is-{year}-01-01.json")
        is_km.json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
        print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
