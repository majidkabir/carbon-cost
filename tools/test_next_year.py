"""Tests that the builders still give valid tables when the year turns:
nothing in them may hold a year or a yearly rate written in.

- HU (tables/hu.py): the EUR/HUF rate of the external-cost charge follows
  209/2013 § 3/A on any ECB history: kept while October's first working
  day's rate is within 5%, replaced from the next 1 January when not.
- FR (fr/build.py): the tariff periods run from the 1 February of the
  newest documents' tariff year to the next 31 January, whatever year.

Usage: python3 tools/test_next_year.py
"""
import contextlib, csv, io, json, os, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "tables"))
sys.path.insert(0, os.path.join(here, "fr"))
import hu  # noqa: E402
import build as fr  # noqa: E402
import gr  # noqa: E402


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


def test_fr_stale():
    """No table for a tariff year an operator's document doesn't reach:
    its prices would be the last year's."""
    d = tempfile.mkdtemp()
    pairs, stations = os.path.join(d, "pairs.csv"), os.path.join(d, "stations.json")
    json.dump({n: [{"gare": n, "lat": 48 + i, "lon": 2.0}] for i, n in enumerate("ABCD")}, open(stations, "w"))
    for y_from, y_read, wrote in (("2026-02-01", "", False), ("2026-02-01", "2027-03-01", True), ("2027-02-01", "", True), ("", "2026-11-04", False)):
        with open(pairs, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["operator", "document", "url", "sha256", "valid_from", "entry", "exit", "class3", "class4", "read_on"])
            w.writerow(["X", "x.pdf", "x", "0" * 64, "2027-02-01", "A", "B", "12", "18", ""])
            w.writerow(["Y", "y.txt", "y", "1" * 64, y_from, "C", "D", "6", "9", y_read])
        out = os.path.join(d, "fr-2027-02-01.json")
        with contextlib.redirect_stdout(io.StringIO()) as said:
            fr.periods(pairs, stations, None, d)
        assert os.path.exists(out) == wrote and ("::warning" in said.getvalue()) != wrote, (y_from, y_read, said.getvalue())
        if wrote:
            os.remove(out)
    for f in (pairs, stations):
        os.remove(f)
    os.rmdir(d)


def test_gr():
    """Greece's year is the one its dated pages give; when they disagree
    (one has next year's prices, another not yet), the build stops."""
    d = tempfile.mkdtemp()
    real, gr.BROWSER = gr.BROWSER, d
    try:
        for aegean, want in (("2027", "2027"), ("2026", None)):
            for sid, text in (("olympia", "Όπως ισχύουν από 01/01/2027"), ("aegean", f"Έναρξη ισχύος του τρέχοντος τιμοκαταλόγου 01 Ιανουαρίου {aegean} – 00:01"),
                              ("attiki", "Νέα Αττική Οδός: Τιμαριθμική προσαρμογή διοδίων τελών 2027")):
                open(os.path.join(d, f"gr-{sid}.html"), "w", encoding="utf-8").write(f"<html><p>{text}</p></html>")
            try:
                got = gr.price_year(d)
            except SystemExit:
                got = None
            assert got == want, (aegean, got)
    finally:
        gr.BROWSER = real
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)


if __name__ == "__main__":
    test_hu()
    test_fr()
    test_fr_stale()
    test_gr()
    print("test_next_year: ok")
