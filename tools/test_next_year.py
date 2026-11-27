"""Tests that the builders still give valid tables when the year turns:
nothing in them may hold a year or a yearly rate written in.

- HU (tables/hu.py): the EUR/HUF rate of the external-cost charge follows
  209/2013 § 3/A on any ECB history: kept while October's first working
  day's rate is within 5%, replaced from the next 1 January when not.
- FR (fr/build.py): the tariff periods run from the 1 February of the
  newest documents' tariff year to the next 31 January, whatever year.

Usage: python3 tools/test_next_year.py
"""
import csv, os, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "tables"))
sys.path.insert(0, os.path.join(here, "fr"))
import hu  # noqa: E402
import build as fr  # noqa: E402


def test_hu():
    d = tempfile.mkdtemp()
    hu.ECB = os.path.join(d, "ecb.csv")
    rows = [("2024-10-01", 397.83), ("2025-10-01", 388.70), ("2026-10-01", 367.18), ("2027-10-01", 370.0), ("2028-10-02", 400.0)]
    with open(hu.ECB, "w") as f:
        f.write("date,CHF,HUF\n" + "".join(f"{day},0.94,{r}\n" for day, r in rows))
    want = {"2026-12-31": 388.60, "2027-01-01": 367.18, "2028-06-01": 367.18, "2029-01-01": 400.0}
    got = {day: hu.eur_huf(day)[0] for day in want}
    os.remove(hu.ECB)
    os.rmdir(d)
    assert got == want, got


def test_fr():
    d = tempfile.mkdtemp()
    pairs = os.path.join(d, "pairs.csv")
    for year in (2026, 2027, 2031):
        with open(pairs, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["url", "valid_from"])
            w.writerows([["a", f"{year - 1}-02-01"], ["b", f"{year}-02-01"], ["c", f"{year}-05-01"], ["d", ""]])
        tables = []
        real, fr.main = fr.main, lambda *a: tables.append((os.path.basename(a[3]), a[5]))
        try:
            fr.periods(pairs, None, None, d)
        finally:
            fr.main = real
        want = [(f"fr-{year}-02-01.json", f"{year}-04-30"), (f"fr-{year}-05-01.json", f"{year + 1}-01-31")]
        assert tables == want, (year, tables)
    os.remove(pairs)
    os.rmdir(d)


if __name__ == "__main__":
    test_hu()
    test_fr()
    print("test_next_year: ok")
